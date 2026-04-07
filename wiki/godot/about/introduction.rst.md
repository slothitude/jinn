# Introduction.Rst

## Overview
Godot Engine is a free, open-source (MIT license), community-driven 2D and 3D game engine. It provides a unified interface for cross-platform development, allowing one-click exports to desktop, mobile, web, and console platforms without royalties or usage restrictions. The engine is backed by the non-profit Godot Foundation. Its official documentation is a collaborative, open effort licensed under Creative Commons Attribution 3.0 (CC BY 3.0).

## Key Patterns
- **Node Initialization:** The standard entry point for logic when a node is first loaded into the Scene Tree is the `_ready()` callback.

```gdscript
func _ready():
    print("Hello world!")
```

```csharp
public override void _Ready()
{
    GD.Print("Hello world!");
}
```

## API Reference
- **`_ready()`:** Virtual method called when the node enters the scene tree. Used for initial setup and initialization.
- **`GD.Print()`:** Prints text to the standard output (console).

## Gotchas
- **Documentation Organization:** The "Manual" section is not designed to be read in order; it is a reference for specific features. 
- **Finding Help:** If you encounter issues, the built-in `Class Reference` (available directly in the script editor) is the fastest way to check API signatures before seeking help on community channels like Discord or Forums.

## Cross-References
- [[Getting Started]] — The recommended launch point for all new users.
- [[Community Tutorials]] — Curated list of external video and text tutorials.
- [[FAQ]] — Frequently asked questions about the engine and its capabilities.
- [[Class Reference]] — The complete, built-in API documentation for all Godot classes, signals, and properties.

---
### Jinn Heuristics
- HEURISTIC: When onboarding, direct users strictly to [[Getting Started]] rather than the broader "Manual" to prevent information overload. — source: Godot
- HEURISTIC: Always check the built-in `Class Reference` within the script editor before searching external sources for API behaviors. — source: Godot