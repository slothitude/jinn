# Class @GDScript

## Overview
`@GDScript` is the global scope namespace for GDScript-specific utility functions, built-in constants, and annotations. Unlike `@GlobalScope`, which is accessible across all Godot scripting languages, the features defined in `@GDScript` are strictly exclusive to the GDScript environment. 

This class acts as the primary toolkit for GDScript developers, providing everything from mathematical constants (`PI`, `INF`), flow-control helpers (`range`), to powerful compiler annotations like `@export` and `@onready` that dictate how the Godot engine initializes and interacts with script variables.

## Key Patterns

- **Pattern 1: Resource Preloading vs Lazy Loading**
  Use `preload` for resources that are always needed (loads at compile time). Use `load` for resources that are conditional or loaded dynamically at runtime.
  ```gdscript
  const STATIC_TEXTURE = preload("res://icon.png") # Compile-time
  
  func _ready():
      var dynamic_texture = load("res://assets/" + level_name + ".png") # Runtime
  ```

- **Pattern 2: Strict Node Initialization**
  Use `@onready` to safely cache scene tree references. This defers variable assignment until the `Node._ready()` function is called, preventing null reference errors.
  ```gdscript
  @onready var sprite: Sprite2D = $Sprite2D
  @onready var rigid_body: RigidBody2D = %RigidBody
  ```

- **Pattern 3: Exposing Variables to the Inspector**
  Use `@export` to make variables adjustable in the Godot Editor inspector dock without altering the script.
  ```gdscript
  @export var speed: float = 200.0
  @export_range(0, 100) var health: int = 100
  ```

## API Reference

### Annotations
- `@export` — Exposes a variable to the Inspector dock.
- `@onready` — Defers variable initialization until the node is ready.
- `@rpc` — Configures a function for Multiplayer RPC (Remote Procedure Call).
- `@icon` — Provides a custom icon for a script in the Editor filesystem.

### Methods
- `Color8(r8: int, g8: int, b8: int, a8: int = 255)` — Returns a `Color` constructed from 8-bit integers (0-255).
- `assert(condition: bool, message: String = "")` — Asserts that the `condition` is `true`. If false, raises an error (ignored in release builds).
- `convert(what: Variant, type: Variant.Type)` — Converts a value to a specified type.
- `dict_to_inst(dictionary: Dictionary)` — Converts a previously serialized dictionary back into an `Object` instance.
- `inst_to_dict(instance: Object)` — Serializes an `Object` instance to a `Dictionary`.
- `is_instance_of(value: Variant, type: Variant)` — Returns `true` if the value is an instance of the given type.
- `len(var: Variant)` — Returns the length of a `Variant` (String, Array, Dictionary, etc.).
- `load(path: String)` — Loads a `Resource` from the filesystem at runtime.
- `preload(path: String)` — Loads a `Resource` from the filesystem at compile time.
- `range(...)` — Returns an `Array` of integers or floats within a specified range.
- `print_debug(...)` — Prints values to the console along with the current stack frame.

### Constants
- `PI` — The mathematical constant Pi (3.14159265358979).
- `TAU` — The mathematical constant Tau (6.28318530717959).
- `INF` — Positive floating-point infinity.
- `NAN` — "Not a Number", an invalid floating-point value.

## Gotchas
- **Compile-Time Constraints of `preload`**: The `preload` function requires a constant string path (`preload("res://icon.png")`). You cannot pass a variable or use string concatenation dynamically with `preload`.
- **Assertion Side-Effects**: Because `assert` is stripped in export/release builds, do not execute functions or mutate state inside the condition (e.g., `assert(apply_damage())`). Use it strictly for debugging logic.

## Cross-References
- [[GlobalScope]] — The counterpart to `@GDScript`; contains global built-in functions available to all languages (C#, GDScript, etc.).
- [[Resource]] — The data type returned by the `load` and `preload` utilities.
- [[Node]] — The primary object type manipulated using `@onready` and scene-tree utilities.
- [[Signal]] — Often used in tandem with `@export` variables to emit state changes.

---
### Jinn Heuristics
- **HEURISTIC:** Favor `@onready` for all node path caching to guarantee the scene tree is fully initialized before references are stored. — *source: Godot*
- **HEURISTIC:** Treat `preload` as a strict dependency declaration. If the resource path is dynamic, fall back to `load`. — *source: Godot*
- **HEURISTIC:** Never wrap state-mutating logic inside `assert()`; it will silently disappear in production builds. — *source: Godot*