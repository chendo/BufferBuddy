# BufferBuddy

BufferBuddy aims to prevent print quality issues when printing over USB with Octoprint. Designed for Marlin, but may work for other firmwares.

**WARNING:** This plugin is still considered **experimental and may cause your printer to hard lock**. I am not responsible for any damage this plugin may cause. **You have been warned.**

Some of you may have noticed print quality issues when printing curved lines over USB, which tends to manifests as zits on the surface layer of a print. I personally noticed this when I upgraded to Cura 4.7.1, which has [a bug](https://github.com/Ultimaker/Cura/issues/8321) that generates extremely dense gcode for curves (potentially exacerbated by certain printer profiles that incorrectly sets too fine of a resolution, which is due to another bug fixed in 4.7). This can be addressed by printing directly from the SD card, however I like the convenience and flexibility of Octoprint.

This is caused when the planner buffer runs out of instructions during a print, which causes printer movement to stall, however the pressure in the hotend will cause undesired extrusion.

Octoprint's default behaviour is to send a command, and wait for an `ok` response from the printer before sending another command. Generally, this is fine and reliable, but during small segments (usually seen in curves), this can cause the planner buffer to underrun.

It's important to note that increasing `BUFSIZE` does not improve print quality when printing over USB with Octoprint by default as the command buffer never holds more than one pending command with Octoprint's default behaviour, but this plugin aims to address that.

For more information, see my blog post on [how I diagnosed the print quality issue when printing with Octoprint](https://chen.do/diagnosing-reduced-print-quality-with-octoprint/), and how I [added buffer monitorin to Marlin](https://chen.do/adding-buffer-monitoring-to-marlin/), which was instrumental in understanding how to fix the issue.

## Do I need it?

If you're not encounting print quality issues, you probably don't need it.

If you have `ADVANCED_OK` output, you can tell if you're running into the issue by observing the number after `P`. For a Marlin configuration where `BLOCK_BUFFER_SIZE=16`, if you see `P15` during a print, that means the planner buffer was empty before it received the command, which means the printer did not have any movement planned and would have stalled.

For a better understanding if your buffers are underrunning, consider using my `M576` command available as [pending pull request](https://github.com/MarlinFirmware/Marlin/pull/19674).

## How it works

This plugin uses the `ADVANCED_OK` feature in Marlin where the `ok` output is extended with `ok N<line number> P<planner buffer remaining> B<command buffer remaining>` to understand the current state of the printer's buffers.

This enables the plugin to understand how many more commands we can send to the printer, and we do so by causing Octoprint to send more commands before it's received an acknowledgement by messing with its internals and thus can break if these internals are changed.

The core algorithm is as follows:

* It parses the `ok` output to understand:
    * How many free slots are left in the printer's command buffer by looking at `B`
    * How many lines are currently in-flight to the printer by checking Octoprint's `comm._current_line` and comparing to the `N<line number>` reported in the `ok` output.
* If:
    * there is more than one slot in the buffer (which we try to keep available), and
    * we don't have more than `BUFSIZE-1` lines inflight
    * and we haven't triggered an extra send too recently
* Then:
    * Check Octoprint's queue to make sure there's something to send
        * If not, trigger `comm._continue_sending` to add something to the queue
    * Trigger the next command to be send by unblocking the `_send_loop` by calling `comm._clear_to_send.set()`

## Limitations

This plugin can only try to keep the command buffers filled.

It cannot make your printer process more commands than the processor is capable of, nor fix underlying communication issues between Octoprint and your printer.

## Requirements

* Marlin 2.x, with `ADVANCED_OK` support.
    * It's important that you also change `TX_BUFFER_SIZE` or `USART_TX_BUF_SIZE` depending on your configuration to at least `32` as `ADVANCED_OK` sends more data.
    * This plugin is more effective with a higher `BUFSIZE`. The default of `4` is generally not enough for this plugin to be useful.

## Tested with

This plugin has only been tested with my Ender 3 v2 running [Smith3D's Marlin fork](https://github.com/smith3d/Marlin/tree/bugfix-2.0.x-Smith3D) which includes improvements specifically for the Ender 3 v2, but should work for any Marlin 2.x firmware with the appropriate configuration.

If you have had success with other printers, please send a pull request and add the details below.

* Ender 3 v2: `BUFSIZE=16, BLOCK_BUFFER_SIZE=16, USART_RX_BUF_SIZE=64, USART_RX_BUF_SIZE=64`

## Setup

Install via the bundled [Plugin Manager](https://docs.octoprint.org/en/master/bundledplugins/pluginmanager.html)
or manually using this URL:

    https://github.com/chendo/BufferBuddy/archive/main.zip

## Configuration

**TODO:** Describe your plugin's configuration options (if any).
