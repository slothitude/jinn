# Complying With Licenses

## Overview
Godot Engine is distributed under the MIT License, allowing free commercial use provided the license and copyright notices are included in derivative projects. This page details how to comply with these attribution requirements, covering both the core engine and the third-party libraries it relies on. Games made with Godot can be released under any license, but must fulfill the MIT license's attribution clause.

## Key Patterns
- **Pattern 1: Static License Inclusion** 
  The MIT license requires including the copyright notice in your game. This can be placed in a credits screen, a dedicated "Third-party Licenses" menu, a physical manual, or an accompanying file (e.g., `GODOT_COPYRIGHT.txt`).
  
- **Pattern 2: Dynamic License Extraction**
  To prevent license text from becoming outdated when updating engine versions, fetch licenses directly from the engine binary using the [[Engine]] singleton.
  ```gdscript
  var engine_license = Engine.get_license_text()
  var third_party_info = Engine.get_license_info()
  ```

- **Pattern 3: Output Logging**
  On platforms where global output logs are accessible (Desktop, Android, HTML5), printing the license via standard output is sufficient (note: this fails on iOS).
  ```gdscript
  print(Engine.get_license_text())
  ```

## API Reference
- `Engine.get_license_text()` — Returns the full MIT license text for the Godot Engine.
- `Engine.get_license_info()` — Returns a dictionary of licenses for third-party components used by the engine.
- `Engine.get_copyright_info()` — Returns an array of copyright information for third-party components.
- `print()` — Writes to standard output; can be used to display licenses on supported platforms.

## Gotchas
- **Third-Party Assets:** Free assets (textures, sounds, fonts, etc.) often have their own attribution licenses. These must be credited alongside the engine's license.
- **Platform Limitations:** Do not rely on output logging (`print()`) for license compliance on iOS, as the global output log is not readable by end-users.
- **Third-Party Code:** Godot includes third-party libraries. While the engine is MIT, these components have their own permissive licenses requiring explicit citation. 

## Cross-References
- [[Engine]] — Singleton class used to dynamically retrieve license and copyright information at runtime.
- [[@GlobalScope]] — Contains the `print()` function used for outputting text to standard logs.

---
### Jinn Heuristics
- HEURISTIC: Dynamically fetch licenses over hardcoding strings. Rely on the [[Engine]] singleton API to prevent outdated license text when updating engine versions. — <source: Godot>