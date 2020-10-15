# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import time
import re
from octoprint.events import eventManager, Events

ADVANCED_OK = re.compile(r"ok (N(?P<line>\d+) )?P(?P<planner_buffer_avail>\d+) B(?P<command_buffer_avail>\d+)")
REPORT_INTERVAL = 2

class BufferBuddyPlugin(octoprint.plugin.SettingsPlugin,
						octoprint.plugin.AssetPlugin,
						octoprint.plugin.TemplatePlugin,
						octoprint.plugin.StartupPlugin,
						):

	def __init__(self):
		self.last_cts = time.time()
		self.last_report = time.time()
		
		self.enabled = False
		self.enabled_streaming = False

		eventManager().subscribe(Events.CONNECTING, self.on_connecting)
		eventManager().subscribe(Events.TRANSFER_STARTED, self.on_transfer_started)
		eventManager().subscribe(Events.PRINT_STARTED, self.on_print_started)
		eventManager().subscribe(Events.PRINT_DONE, self.on_print_finish)
		eventManager().subscribe(Events.PRINT_FAILED, self.on_print_finish)
	
	def on_connecting(self, event, payload):
		self._logger.info("connect hook")
		self.command_buffer_size = 0
		self.planner_buffer_size = 0

	def on_transfer_started(self, event, payload):
		self.sd_stream_current_inflight = 0
		self.reset_statistics()

	def on_print_started(self, event, payload):
		self.reset_statistics()

	def on_print_finish(self, event, payload):
		if self.should_report_statistics:
			self.report_statistics()

	def reset_statistics(self):
		self.command_underruns = 0
		self.planner_underruns = 0
		self.clear_to_sends = 0
		self.did_resend = False

	def report_statistics(self):
		message = "Planner underruns: {}\nCommand underruns: {}\nSends triggered: {}".format(self.planner_underruns, self.command_underruns, self.clear_to_sends)
		self._logger.info(message)
		toast = {
			"message_type": "toast",
			"title": "BufferBuddy statistics",
			"message": message
		}
		self._plugin_manager.send_plugin_message(self._identifier, toast)

	def set_buffer_sizes(self, planner_buffer_size, command_buffer_size):
		self.planner_buffer_size = planner_buffer_size
		self.command_buffer_size = command_buffer_size
		self.max_inflight = command_buffer_size - 1
		self._logger.info("Detected planner buffer size as {}, command buffer size as {}, setting max_inflight to {}".format(planner_buffer_size, command_buffer_size, self.max_inflight))

	##~~ StartupPlugin mixin

	def on_after_startup(self):
		self.apply_settings()
		self._logger.info("BufferBuddy ready")

	##~~ SettingsPlugin mixin

	def get_settings_defaults(self):
		return dict(
			enabled=True,
			enabled_streaming=True,
			min_cts_interval=0.1,
			should_report_statistics=True,
			sd_max_inflight=40, # Must be safe margin below Octoprint's resend buffer
		)

	def on_settings_save(self, data):
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
		self.apply_settings()

	def apply_settings(self):
		self.enabled = self._settings.get_boolean(["enabled"])
		self.enabled_streaming = self._settings.get_boolean(["enabled_streaming"])
		self.min_cts_interval = self._settings.get_float(["min_cts_interval"])
		self.sd_stream_max_inflight = self._settings.get_float(["sd_stream_max_inflight"])
		self.should_report_statistics = self._settings.get_boolean(["should_report_statistics"])

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

		# We don't want to run unless we're printing.
		if not comm.isPrinting():
			return line
		
		if comm.isStreaming():
			if not self.enabled_streaming:
				return line

			if comm._resendActive:
				# self._logger.warn("resend detected")
				self.did_resend = True

				# FIXME: This logic needs to be verified
				if self.sd_stream_max_inflight > self.sd_stream_current_inflight:
					self._logger.warn("Had {} lines inflight before error, setting sd stream max to {}".format(self.sd_stream_current_inflight, self.sd_stream_max_inflight - 10))
					self.sd_stream_max_inflight = self.sd_stream_current_inflight - 10 # to be safe
					self.sd_stream_current_inflight = 0
			elif self.did_resend: # Once resend is over, scale back max_inflight a bit
				self.sd_stream_max_inflight -= 1
				self.did_resend = False

			
		# Don't do anything fancy when we're in a middle of a resend
		if comm._resendActive:
			return line


		if "ok " in line:
			matches = ADVANCED_OK.search(line)

			if matches is None or matches.group('line') is None:
				return line
				
			ok_line_number = int(matches.group('line'))
			current_line_number = comm._current_line
			command_buffer_avail = int(matches.group('command_buffer_avail'))
			planner_buffer_avail = int(matches.group('planner_buffer_avail'))
			inflight = current_line_number - ok_line_number
			queue_size = comm._send_queue._qsize()

			should_report = False
			should_send = False

			# detect underruns
			if command_buffer_avail == self.command_buffer_size - 1:
				self.command_underruns += 1

			if planner_buffer_avail == self.planner_buffer_size - 1:
				self.planner_underruns += 1

			if (time.time() - self.last_report) > REPORT_INTERVAL:
				should_report = True

			if command_buffer_avail > 1: # aim to keep at least one spot free
				if comm.isStreaming() and inflight < self.sd_stream_max_inflight:
				if inflight < self.max_inflight and (time.time() - self.last_cts) > self.min_cts_interval:
					should_send = True

			if should_send and self.enabled:
				# If the command queue is empty, triggering clear_to_send won't do anything
				# so we try to make sure something's in there
				if queue_size == 0: 
					self._logger.debug("command queue empty, prod comm to send more with _continue_sending()")
					comm._continue_sending()
				self._logger.debug("detected available command buffer, triggering a send")
				# this enables the send loop to send if it's waiting
				comm._clear_to_send.set() # Is there a point calling this if _clear_to_send is at max?
				self.clear_to_sends += 1
				self.last_cts = time.time()
				should_report = True

			if should_report:
				self._logger.debug("current line: {} ok line: {} buffer avail: {} inflight: {} cts: {} cts_max: {} queue: {}".format(current_line_number, ok_line_number, command_buffer_avail, inflight, comm._clear_to_send._counter, comm._clear_to_send._max, queue_size))
				self.last_report = time.time()

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


# If you want your plugin to be registered within OctoPrint under a different name than what you defined in setup.py
# ("OctoPrint-PluginSkeleton"), you may define that here. Same goes for the other metadata derived from setup.py that
# can be overwritten via __plugin_xyz__ control properties. See the documentation for that.
__plugin_name__ = "BufferBuddy"

# Starting with OctoPrint 1.4.0 OctoPrint will also support to run under Python 3 in addition to the deprecated
# Python 2. New plugins should make sure to run under both versions for now. Uncomment one of the following
# compatibility flags according to what Python versions your plugin supports!
#__plugin_pythoncompat__ = ">=2.7,<3" # only python 2
#__plugin_pythoncompat__ = ">=3,<4" # only python 3
#__plugin_pythoncompat__ = ">=2.7,<4" # python 2 and 3

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = BufferBuddyPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
		"octoprint.comm.protocol.gcode.received": __plugin_implementation__.gcode_received,
	}

