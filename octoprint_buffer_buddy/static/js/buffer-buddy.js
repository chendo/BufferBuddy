/*
 * View model for BufferBuddy
 *
 * Author: chendo
 * License: AGPLv3
 */
$(function() {
    function BufferBuddyViewModel(parameters) {
        var self = this;

        // assign the injected parameters, e.g.:
        self.settingsViewModel = parameters[0];

        self.status = ko.observable('Initialising...')
        self.state = ko.observable('initialising')
        self.enabled = ko.observable(false)
        self.advancedOkDetected = ko.observable(false)

        self.plannerBufferSize = ko.observable('0')
        self.commandBufferSize = ko.observable('0')
        self.inflightTarget       = ko.observable('0')

        self.commandBufferAvail = ko.observable('0')
        self.commandUnderrunsDetected = ko.observable('0')

        self.plannerBufferAvail = ko.observable('0')
        self.plannerUnderrunsDetected = ko.observable('0')

        self.ctsTriggered = ko.observable('0')

        self.currentLineNumber = ko.observable('0')
        self.ackedLineNumber = ko.observable('0')
        self.inflight = ko.observable('0')
        self.resendsDetected = ko.observable('0')
        self.sendQueueSize = ko.observable('0')

        self.onDataUpdaterPluginMessage = function (plugin, data) {
            if (plugin !== "buffer_buddy") {
                return;
            }
            
            var type = data.type
            var message = data.message

            if (type == 'update') {
                self.commandBufferAvail(message.command_buffer_avail.toString())
                self.commandUnderrunsDetected(message.command_underruns_detected.toString())
        
                self.plannerBufferAvail(message.planner_buffer_avail.toString())
                self.plannerUnderrunsDetected(message.planner_underruns_detected.toString())
                self.ctsTriggered(message.cts_triggered.toString())
        
                self.currentLineNumber(message.current_line_number.toString())
                self.ackedLineNumber(message.acked_line_number.toString())
                self.inflight(message.inflight.toString())
                self.resendsDetected(message.resends_detected.toString())
                self.sendQueueSize(message.send_queue_size.toString())

            } else if (type == 'status') { 
                self.status(message)
            } else if (type == 'state') {
                self.setState(message)
            }
        }

        self.requestData = function () {
            self.get()
                .done(self.fromResponse)
        }

        self.fromResponse = function (response) {
            self.setState(response.state)
        }

        self.setState = function (config) {
            self.enabled(config.enabled)
            self.advancedOkDetected(config.advanced_ok_detected)
            self.state(config.state)
            self.plannerBufferSize(config.planner_buffer_size.toString())
            self.commandBufferSize(config.command_buffer_size.toString())
            self.inflightTarget(config.inflight_target.toString())

            if (config.advanced_ok_detected) {
                self.status('Ready')
            }
        }

        self.get = function () {
            return OctoPrint.plugins.base.get(OctoPrint.plugins.base.getSimpleApiUrl("buffer_buddy"))
        }
        self.onStartup = self.onUserLoggedIn = self.onUserLoggedOut = self.onEventSettingsUpdated = function() {
            self.requestData()
        }

        self.openSettings = function () {
            $('a#navbar_show_settings').click()
            $('li#settings_plugin_buffer_buddy_link a').click()
        }

    }

    /* view model class, parameters for constructor, container to bind to
     * Please see http://docs.octoprint.org/en/master/plugins/viewmodels.html#registering-custom-viewmodels for more details
     * and a full list of the available options.
     */
    OCTOPRINT_VIEWMODELS.push({
        construct: BufferBuddyViewModel,
        // ViewModels your plugin depends on, e.g. loginStateViewModel, settingsViewModel, ...
        dependencies: [ "settingsViewModel" ],
        // Elements to bind to, e.g. #settings_plugin_buffer-buddy, #tab_plugin_buffer-buddy, ...
        elements: [ "#sidebar_plugin_buffer_buddy", /* ... */ ]
    });
});
