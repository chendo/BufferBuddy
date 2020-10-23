(function (global, factory) {
  if (typeof define === "function" && define.amd) {
      define(["OctoPrintClient"], factory);
  } else {
      factory(global.OctoPrintClient);
  }
})(this, function(OctoPrintClient) {
  var OctoPrintBufferBuddyClient = function(base) {
      this.base = base;
  };

  OctoPrintBufferBuddyClient.prototype.get = function(refresh, opts) {
      return this.base.get(this.base.getSimpleApiUrl("buffer_buddy"), opts);
  };

  OctoPrintBufferBuddyClient.prototype.clear = function(opts) {
      return this.base.simpleApiCommand("buffer_buddy", "clear", {}, opts);
  };

  OctoPrintClient.registerPluginComponent("buffer_buddy", OctoPrintBufferBuddyClient);
  return OctoPrintBufferBuddyClient;
});
