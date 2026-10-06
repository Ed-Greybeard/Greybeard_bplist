# Binary Plist Viewer

A desktop viewer using only Python's standard library: `tkinter`, `plistlib`, and related modules. Requires Python 3.9+ with Tk support. Some Linux distributions package Tk separately as `python3-tk`.

```sh
python3 bplist_viewer.py
python3 bplist_viewer.py /path/to/file.bplist
```

Open binary (`bplist00`) or XML plists regardless of filename extension. Expand/collapse nodes using the tree arrows, keyboard arrows, or toolbar. Select a node to see its full value and path. Binary data is displayed as Base64 and hexadecimal. UID references are displayed as values; NSKeyedArchiver objects are not automatically unarchived.

Regex search checks each node's key, path, type, and complete value (including data encodings). Press Enter or Search, then Previous/Next or Shift-F3/F3 to cycle through matching nodes in tree order. Each node appears once in the results even if multiple fields match. Search opens collapsed ancestors. Ignore case is enabled by default. Changing the pattern or case option clears previous results; press Search again.

Export JSON writes UTF-8 indented JSON. Types JSON cannot represent use tagged objects:

- Data: `{"$type": "data", "base64": "..."}`
- Date: `{"$type": "date", "value": "2026-10-06T12:00:00Z"}` (naive plist dates are UTC)
- UID: `{"$type": "uid", "value": 42}`
- Non-finite real: `{"$type": "real", "value": "inf"}` (or `-inf` / `nan`)

These tags are export conventions, not a lossless interchange schema: ordinary dictionaries could contain identical keys. Text export lists every path, type, and full value, with strings quoted and newlines escaped. Shared containers are shown at each path; cycles are marked in the tree/text export and rejected for JSON export. Export cannot overwrite the opened source file.

Parsing follows the standard-library implementation, so unsupported binary format versions/types produce an error. The viewer loads the full file and tree into memory; very large files or costly regex patterns may pause the UI.

Format references:

- [Apple's binary plist implementation and format layout](https://github.com/apple/swift-corelibs-foundation/blob/main/Sources/CoreFoundation/CFBinaryPList.c)
- [Python plistlib documentation](https://docs.python.org/3/library/plistlib.html)

Run verification with `python3 -m unittest discover -s tests -v`.

## Example file

```sh
python3 bplist_viewer.py examples/country_details.bplist
```

The country demonstration includes nested profiles, city/language arrays, Unicode names, booleans, integers, real numbers, a date, binary data, a UID, empty containers, and a long value. Population and area figures are rounded illustrative values, not current statistics.

Try regex searches for `Europe`, `Tokyo|Paris|Berlin`, `^EUR$`, or `日本|Brasília`, then step through the results. The `feature_examples` branch contains additional suggested searches. Export the file as JSON to see how data, dates, and UID values are represented.
