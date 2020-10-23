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

        // TODO: Implement your plugin's view model here.

        self.status = ko.observable('Ready')
        self.state = ko.observable('ready')
        self.enabled = ko.observable(false)

        self.plannerBufferSize = ko.observable('?')
        self.commandBufferSize = ko.observable('?')
        self.inflightTarget       = ko.observable('?')

        self.commandBufferAvail = ko.observable('?')
        self.commandUnderrunsDetected = ko.observable('?')

        self.plannerBufferAvail = ko.observable('?')
        self.plannerUnderrunsDetected = ko.observable('?')
        self.ctsTriggered = ko.observable('?')

        self.currentLineNumber = ko.observable('?')
        self.ackedLineNumber = ko.observable('?')
        self.inflight = ko.observable('?')
        self.resendsDetected = ko.observable('?')
        self.sendQueueSize = ko.observable('?')

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
            } else if (type ==  'state') {
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
            self.state(config.state)
            self.plannerBufferSize(config.planner_buffer_size.toString())
            self.commandBufferSize(config.command_buffer_size.toString())
            self.inflightTarget(config.inflight_target.toString())
        }

        self.get = function () {
            return OctoPrint.plugins.base.get(OctoPrint.plugins.base.getSimpleApiUrl("buffer_buddy"))
        }

        self.onStartup = self.onUserLoggedIn = self.onUserLoggedOut = function() {
            window.buffer_buddy = self
            self.requestData()
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
