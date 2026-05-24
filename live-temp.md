Live Temperature Findings

  We confirmed the Thor live video path and the live temperature path are separate from the app’s normal decoded video
  frames.

  The app can show live video via Windows/OpenCV, but the decoded frames do not contain usable radiometric data. The
  live temperature payload was found in USB traffic captured with Wireshark/USBPcap.

  Captured Packet Format
  From the working thor_packet.txt / USBPcap capture:

  - Total extracted packet bytes: 98343
  - Temperature header offset: 0x1d
  - Thermal payload offset: 0x27
  - Marker/header bytes: ff 00 ff 00 ff 00 ff 00 ff 00
  - Thermal shape: 256 x 192
  - Encoding: little-endian uint16
  - Unit: Kelvin * 10, converted with C = value / 10 - 273.15
  - Payload size: 256 * 192 * 2 = 98304 bytes

  Example decoded values from a real capture:

  first 8 K10: [3096, 3098, 3096, 3096, 3094, 3096, 3094, 3097]
  center C: 36.65
  min C: 35.65 at (4, 111)
  max C: 37.55 at (238, 175)
  mean C: 36.52

  What Works Now
  We added parser/test code that can decode the temperature frame from a USBPcap/Wireshark capture. The app can load/
  tail a .pcap/.pcapng capture file and use the latest decoded thermal frame for hover temperature in the Live tab.

  The hover mapping is:

  - Visible video frame: typically 640 x 480
  - Thermal frame: 256 x 192
  - Coordinates are scaled from preview/video space into thermal space.
  - Hover temperature is read from the latest decoded 256 x 192 temperature frame.

  Important Limitation
  The temperature data has not been found inside the normal decoded camera image returned by OpenCV/Media Foundation. It
  appears in the USB traffic before or outside the standard decoded video frame path.

  On Windows, the Thor camera interface is already owned by the system UVC driver / Media Foundation. A normal app
  generally cannot also open the same USB interface and read raw transfer packets directly without replacing or
  bypassing the camera driver.

  Standalone Options
  Practical options identified:

  - Use USBPcap as a passive capture backend, launched by the app instead of manually using Wireshark.
  - Investigate whether Thor exposes a separate vendor-specific USB interface carrying temperature data. If yes, direct
    USB access may be possible.
  - If the temperature data is only on the same UVC stream/interface, direct USB reads would likely conflict with
    Windows camera access unless using a custom/lower-level driver approach.

  Conclusion
  We can reliably decode live temperature from USB captures. The remaining engineering question is transport: whether we
  can access the raw temperature stream without USBPcap. That depends on whether the payload is on a separate interface/
  endpoint or only embedded in the UVC traffic already claimed by Windows.