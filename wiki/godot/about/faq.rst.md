# Faq.Rst

## Overview
Godot is a free and open-source MIT-licensed engine usable for any purpose (commercial, personal, non-profit). The engine and editor support a wide array of desktop, mobile, and web platforms. Development primarily relies on the custom-built [[GDScript]] language, though [[C#]] and [[C++]] are officially supported, with further languages available via [[GDExtension]].

## Key Patterns
- **Platform Duality:** The editor supports Windows, macOS, Linux, \*BSD, and experimentally Android/Web. Export targets expand to include iOS. Apple Silicon (ARM64) and x86_64 are natively supported on macOS.
- **Language Architecture:** [[GDScript]] was engineered specifically for Godot to reduce complexity and maintenance overhead. It avoids the bottlenecks of integrating third-party VMs (like Python or Lua) by natively handling threading, class extending, and built-in vector math types (e.g., [[Vector3]], [[Transform3D]]).
- **Licensing Structure:** The engine core uses the permissive MIT license. Documentation and logos use Creative Commons Attribution 3.0 (CC BY 3.0).

## API Reference
- **MIT License:** Grants unlimited rights to download, modify, and distribute Godot commercially and non-commercially. Requires retaining copyright notices (`LICENSE.txt`, `COPYRIGHT.txt`).
- **CC BY 3.0:** Applies to documentation and logos; requires attribution to "Juan Linietsky, Ariel Manzur and the Godot Engine community."
- **GDExtension:** The API framework allowing third-party languages (like Python or Nim) to integrate with the engine without modifying the core.

## Gotchas
- **C# Web Export:** [[C#]] is currently unsupported for Web platform exports.
- **Deprecated Platforms:** Universal Windows Platform (UWP) was deprecated by Microsoft and removed in Godot 4. It remains available only in the Godot 3 branch.
- **Third-Party Licenses:** While Godot core is MIT, some included third-party libraries in the source repository may have different licenses.

## Cross-References
- [[GDScript]] — The recommended, natively optimized scripting language for rapid development and prototyping.
- [[CSharp]] — Officially supported, but lacks web export capabilities and is newer to the engine.
- [[GDExtension]] — The system used to bind third-party languages (Python, Nim) to Godot.
- [[Export]] — Platform deployment targets and templates.
- [[Vector3]] — Native math types heavily optimized within the custom GDScript environment.

---
### Jinn Heuristics
- HEURISTIC: Evaluate [[GDScript]] for a minimum of three days before defaulting to [[CSharp]] or C++; its native integration significantly reduces boilerplate and Time-To-Market (TTM). — <source: Godot>
- HEURISTIC: Do not rely on C# if your primary deployment target is the Web platform. — <source: Godot>
- HEURISTIC: Use [[GDExtension]] for language integrations rather than waiting for native engine support for specific scripting VMs. — <source: Godot>