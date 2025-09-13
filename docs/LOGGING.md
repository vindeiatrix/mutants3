# World-Load Logging

Env vars:
- `WORLD_DEBUG=1` → enable DEBUG logs.
- `WORLD_STRICT=1` → raise if no world files discovered.

### Log Catalogue

- **discover_world_years** (DEBUG)  
  `[world] discover_world_years dir=%(dir)s years=%(years)s`

- **load_year** (DEBUG)  
  `[world] load_year request=%(year)d path=%(path)s cwd=%(cwd)s`

- **load_nearest_year** (INFO)  
  `[world] load_nearest_year requested=%(target)d chosen=%(chosen)d dir=%(dir)s`

- **create_minimal_world** (WARNING)  
  `[world] create_minimal_world reason=%(reason)s cwd=%(cwd)s target_dir=%(dir)s`

- **build_room_vm** (DEBUG)  
  `[room] build_room_vm pos=%(pos)s (year=%(year)d,x=%(x)d,y=%(y)d)`

### Example Session

```
INFO [world] no world jsons found; cwd=/Users/mike/dev/mutants3-main world_dir=/…/state/world
WARNING [world] create_minimal_world reason=no_worlds_discovered cwd=/… target_dir=/…/state/world
DEBUG [world] discover_world_years dir=/…/state/world years=[]
DEBUG [world] load_year request=2000 path=/…/state/world/2000.json cwd=/…
INFO [world] load_nearest_year requested=1999 chosen=2000 dir=/…/state/world
DEBUG [room] build_room_vm pos=[2000,12,-4] (year=2000,x=12,y=-4)
```
