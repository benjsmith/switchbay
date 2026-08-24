# Switch Bay Sketch (companion)

Second VSIX. Not packaged with the main Switch Bay plugin.

Custom editor for Excalidraw (then drawio) scenes stored at:

```
<workspace>/.workbench/sketches/<id>.json
```

PNG export (same contract as `src/switchbay/sketches.py`):

```
<workspace>/wiki/figures/_assets/<id>.png
```

The main plugin's graph "To sketch" / `@switchbay /sketch` only writes
these files and asks you to install this companion to edit them.

Not implemented on this spike yet — file-format contract only.
