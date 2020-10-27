# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
from octoprint.util import monotonic_time
import time
import re
import flask
from octoprint.events import eventManager, Events

ADVANCED_OK = re.compile(r"ok (N(?P<line>\d+) )?P(?P<planner_buffer_avail>\d+) B(?P<command_buffer_avail>\d+)")
REPORT_INTERVAL = 1 # seconds
POST_RESEND_WAIT = 0 # seconds
INFLIGHT_TARGET_MAX = 45 # Octoprint has a hard limit of 50 entries in the buffer for resends so it must be less than that, with a buffer

class BufferBuddyPlugin(octoprint.plugin.SettingsPlugin,
						octoprint.plugin.AssetPlugin,
						octoprint.plugin.TemplatePlugin,
						octoprint.plugin.SimpleApiPlugin,
						octoprint.plugin.StartupPlugin
						):

	def __init__(self):
		# Set variables that we may use before we can pull the settings etc
		self.last_cts = 0
		self.last_report = 0
		
		self.enabled = False

		self.state = 'ready'

		self.min_cts_interval = 1.0 

		eventManager().subscribe(Events.CONNECTING, self.on_connecting)
		eventManager().subscribe(Events.TRANSFER_STARTED, self.on_transfer_started)
		eventManager().subscribe(Events.TRANSFER_DONE, self.on_print_finish)
		eventManager().subscribe(Events.TRANSFER_FAILED, self.on_print_finish)
		eventManager().subscribe(Events.PRINT_STARTED, self.on_print_started)
		eventManager().subscribe(Events.PRINT_DONE, self.on_print_finish)
		eventManager().subscribe(Events.PRINT_FAILED, self.on_print_finish)

		self.reset_statistics()
	
	def on_connecting(self, event, payload):
		self.command_buffer_size = 0
		self.planner_buffer_size = 0

	def on_transfer_started(self, event, payload):
		self.reset_statistics()
		self.state = 'transferring'
		self.send_plugin_state()

	def on_print_started(self, event, payload):
		self.reset_statistics()
		self.state = 'printing'
		self.send_plugin_state()

	def on_print_finish(self, event, payload):
		self.set_status('Ready')
		self.state = 'ready'
		self.send_plugin_state()

	def reset_statistics(self):
		self.command_underruns_detected = 0
		self.planner_underruns_detected = 0
		self.resends_detected = 0
		self.clear_to_sends_triggered = 0
		self.did_resend = False

	def set_buffer_sizes(self, planner_buffer_size, command_buffer_size):
		self.planner_buffer_size = planner_buffer_size
		self.command_buffer_size = command_buffer_size
		self.inflight_target = min(command_buffer_size - 1, INFLIGHT_TARGET_MAX)
		self._logger.info("Detected planner buffer size as {}, command buffer size as {}, setting inflight_target to {}".format(planner_buffer_size, command_buffer_size, self.inflight_target))
		self.send_plugin_state()


	##~~ StartupPlugin mixin

	def on_after_startup(self):
		self.apply_settings()
		self._logger.info("BufferBuddy ready")

	##~~ SettingsPlugin mixin

	def get_settings_defaults(self):
		return dict(
			enabled=True,
			min_cts_interval=0.1,
			sd_inflight_target=4,
		)

	def on_settings_save(self, data):
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
		self.apply_settings()

	def apply_settings(self):
		self.enabled = self._settings.get_boolean(["enabled"])
		self.min_cts_interval = self._settings.get_float(["min_cts_interval"])
		self.sd_inflight_target = self._settings.get_int(["sd_inflight_target"])

	##~~ Frontend stuff
	def send_message(self, type, message):
		self._plugin_manager.send_plugin_message(self._identifier, {"type": type, "message": message})

	def set_status(self, message):
		self.send_message("status", message)

	def send_plugin_state(self):
		self.send_message("state", self.plugin_state())

	def plugin_state(self):
		return {
			"planner_buffer_size": self.planner_buffer_size,
			"command_buffer_size": self.command_buffer_size,
			"inflight_target": self.inflight_target,
			"state": self.state,
			"enabled": self.enabled,
		}

	def on_api_get(self, request):
		return flask.jsonify(state=self.plugin_state())

	def get_api_commands(self):
		return dict(clear=[])

	def on_api_command(self, command, data):
		# No commands yet
		return None

	##~~ Core logic

	# Assumptions: This is never called concurrently, and we are free to access anything in comm
	# FIXME: Octoprint considers the job finished when the last line is sent, even when there are lines inflight
	def gcode_received(self, comm, line, *args, **kwargs):				
		# Try to figure out buffer sizes for underrun detection by looking at the N0 M110 N0 response
		# Important: This runs before on_after_startup
		if self.planner_buffer_size == 0 and "ok N0 " in line:
			matches = ADVANCED_OK.search(line)
			if matches:
				# ok output always returns BLOCK_BUFFER_SIZE - 1 due to 
				#     FORCE_INLINE static uint8_t moves_free() { return BLOCK_BUFFER_SIZE - 1 - movesplanned(); }
				# for whatever reason
				planner_buffer_size = int(matches.group('planner_buffer_avail')) + 1
				# We add +1 here as ok will always return BUFSIZE-1 as we've just sent it a command
				command_buffer_size = int(matches.group('command_buffer_avail')) + 1
				self.set_buffer_sizes(planner_buffer_size, command_buffer_size)
				self.set_status('Buffer sizes detected')

		if self.did_resend and not comm._resendActive:
			self.did_resend = False
			self.set_status('Resend over, resuming...')

		if "ok " in line:
			matches = ADVANCED_OK.search(line)

			if matches is None or matches.group('line') is None:
				return line
				
			ok_line_number = int(matches.group('line'))
			current_line_number = comm._current_line
			command_buffer_avail = int(matches.group('command_buffer_avail'))
			planner_buffer_avail = int(matches.group('planner_buffer_avail'))
			queue_size = comm._send_queue._qsize()
			inflight_target = self.sd_inflight_target if comm.isStreaming() else self.inflight_target
			inflight = current_line_number - ok_line_number
			inflight += comm._clear_to_send._counter # If there's a clear_to_send pending, we need to count it as inflight cause it will be soon

			should_report = False
			should_send = False

			# If we're in a resend state, try to lower inflight commands by consuming ok's
			if comm._resendActive and self.enabled:
				if not self.did_resend:
					self.resends_detected += 1
					self.did_resend = True
					self.set_status('Resend detected, backing off')
				self.last_cts = monotonic_time() + POST_RESEND_WAIT # Hack to delay before resuming CTS after resend event to give printer some time to breathe
				if inflight > (inflight_target / 2):
					self._logger.warn("using a clear to decrease inflight, inflight: {}, line: {}".format(inflight, line))
					comm._ok_timeout = monotonic_time() + 0.05 # Reduce the timeout in case we eat too many OKs
					return None

			# detect underruns if printing
			if not comm.isStreaming():
				if command_buffer_avail == self.command_buffer_size - 1:
					self.command_underruns_detected += 1

				if planner_buffer_avail == self.planner_buffer_size - 1:
					self.planner_underruns_detected += 1

			if (monotonic_time() - self.last_report) > REPORT_INTERVAL:
				should_report = True

			if command_buffer_avail > 1: # aim to keep at least one spot free
				if inflight < inflight_target and (monotonic_time() - self.last_cts) > self.min_cts_interval:
					should_send = True

			if should_send and self.enabled:
				# Ensure _clear_to_send._max is at least 2, otherwise triggering _clear_to_send won't do anything
				if comm._clear_to_send._max < 2:
					self._logger.warn("setting 'ok buffer size' / comm._clear_to_send._max to 2 cause plugin doesn't work at 1")
					comm._clear_to_send._max = 2

				# If the command queue is empty, triggering clear_to_send won't do anything
				# so we try to make sure something's in there
				if queue_size == 0: 
					self._logger.debug("command queue empty, prod comm to send more with _continue_sending()")
					comm._continue_sending()
				self._logger.debug("detected available command buffer, triggering a send")
				# this enables the send loop to send if it's waiting
				comm._clear_to_send.set() # Is there a point calling this if _clear_to_send is at max?
				self.clear_to_sends_triggered += 1
				self.last_cts = monotonic_time()
				should_report = True

			if should_report:
				self.send_message("update", {
					"current_line_number": current_line_number,
					"acked_line_number": ok_line_number,
					"inflight": inflight,
					"planner_buffer_avail": planner_buffer_avail,
					"command_buffer_avail": command_buffer_avail,
					"resends_detected": self.resends_detected,
					"planner_underruns_detected": self.planner_underruns_detected,
					"command_underruns_detected": self.command_underruns_detected,
					"cts_triggered": self.clear_to_sends_triggered,
					"send_queue_size": queue_size,
				})
				self._logger.debug("current line: {} ok line: {} buffer avail: {} inflight: {} cts: {} cts_max: {} queue: {}".format(current_line_number, ok_line_number, command_buffer_avail, inflight, comm._clear_to_send._counter, comm._clear_to_send._max, queue_size))
				self.last_report = monotonic_time()
				self.set_status('Monitoring')

		return line

	##~~ AssetPlugin mixin

	def get_assets(self):
		# Define your plugin's asset files to automatically include in the
		# core UI here.
		return dict(
			js=["js/buffer-buddy.js"],
			css=["css/buffer-buddy.css"],
			less=["less/buffer-buddy.less"]
		)

	##~~ Softwareupdate hook

	def get_update_information(self):
		# Define the configuration for your plugin to use with the Software Update
		# Plugin here. See https://docs.octoprint.org/en/master/bundledplugins/softwareupdate.html
		# for details.
		return dict(
			buffer_buddy=dict(
				displayName="BufferBuddy Plugin",
				displayVersion=self._plugin_version,

				# version check: github repository
				type="github_release",
				user="chendo",
				repo="BufferBuddy",
				current=self._plugin_version,

				# update method: pip
				pip="https://github.com/chendo/BufferBuddy/archive/{target_version}.zip"
			)
		)

	##~~ AssetPlugin
	def get_assets(self):
		return dict(
			js=["js/buffer-buddy.js"]
		)

	##~~ TemplatePlugin
	def get_template_configs(self):
		return [
				dict(type="sidebar", custom_bindings=False),
				dict(type="settings", custom_bindings=False)
		]

# If you want your plugin to be registered within OctoPrint under a different name than what you defined in setup.py
# ("OctoPrint-PluginSkeleton"), you may define that here. Same goes for the other metadata derived from setup.py that
# can be overwritten via __plugin_xyz__ control properties. See the documentation for that.
__plugin_name__ = "BufferBuddy"

# Starting with OctoPrint 1.4.0 OctoPrint will also support to run under Python 3 in addition to the deprecated
# Python 2. New plugins should make sure to run under both versions for now. Uncomment one of the following
# compatibility flags according to what Python versions your plugin supports!
#__plugin_pythoncompat__ = ">=2.7,<3" # only python 2
#__plugin_pythoncompat__ = ">=3,<4" # only python 3
__plugin_pythoncompat__ = ">=2.7,<4" # python 2 and 3

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = BufferBuddyPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
		"octoprint.comm.protocol.gcode.received": __plugin_implementation__.gcode_received,
	}

