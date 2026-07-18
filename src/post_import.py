"""
Post-import script for Joplin.

Since JEX import cannot set userData (which the Repeating TODOs plugin
uses for recurrence), we generate a script that runs inside Joplin's
JavaScript plugin context to set the recurrence data after import.

This generates a JSON mapping file that a Joplin plugin or external
script can consume to apply recurrence settings.
"""

import json
import os
from .recurrence_parser import RecurrenceData


def generate_post_import_data(
    recurrence_map: dict[str, RecurrenceData],
    output_dir: str,
) -> str:
    """
    Generate post-import data files.

    Writes:
      - {output_dir}/recurrence_data.json  (note_id → RecurrenceData)
      - {output_dir}/apply_recurrence.md   (instructions)

    Returns the path to the JSON file.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Write the recurrence data as JSON
    rec_data = {
        note_id: rec.to_dict()
        for note_id, rec in recurrence_map.items()
    }

    json_path = os.path.join(output_dir, "recurrence_data.json")
    with open(json_path, "w") as f:
        json.dump(rec_data, f, indent=2)

    # Write instructions
    instructions = os.path.join(output_dir, "apply_recurrence.md")
    with open(instructions, "w") as f:
        f.write("""# Post-Import: Apply Recurrence Data

## What This Is

Your JEX import contains recurring tasks, but the JEX format cannot set the
`userData` that the **Repeating TODOs** plugin needs for recurrence rules.

This directory contains `recurrence_data.json` — a mapping of note UUIDs to
their recurrence settings.

## How to Apply

### Option A: Use the Joplin Data API (Manual Script)

1. Open Joplin
2. Go to **Tools → Options → Plugins** and install the **Repeating TODOs** plugin
3. Open **Help → Toggle Developer Tools** to access the console
4. Run the following script in the console (replace `<path>` with the full
   path to `recurrence_data.json`):

```javascript
// Copy this into the Joplin Developer Tools console
(async () => {
  const joplin = require('api');
  const fs = require('fs-extra');
  
  const data = JSON.parse(
    fs.readFileSync('<path>/recurrence_data.json', 'utf-8')
  );
  
  for (const [noteId, recurrence] of Object.entries(data)) {
    await joplin.data.userDataSet(
      1, // ModelType.Note
      noteId,
      'recurrence',
      recurrence
    );
    
    // Also tag with 'recurring'
    const tags = await joplin.data.get(['tags'], { fields: ['id', 'title'] });
    let recurringTag = tags.items.find(t => t.title === 'recurring');
    if (!recurringTag) {
      recurringTag = await joplin.data.post(['tags'], null, { title: 'recurring' });
    }
    await joplin.data.post(
      ['tags', recurringTag.id, 'notes'],
      null,
      { id: noteId }
    );
  }
  
  console.log(`Applied recurrence to ${Object.keys(data).length} notes`);
})();
```

### Option B: Use the Repeating TODOs Plugin UI

For each recurring task:
1. Open the note in Joplin
2. Click the recurrence icon in the toolbar
3. Configure the recurrence manually using the values from
   `recurrence_data.json`

## Recurrence Data Format

Each entry maps a note UUID to:
```json
{
  "enabled": true,
  "interval": "day",
  "intervalNumber": 1,
  "weekSunday": false,
  "weekMonday": true,
  ...
  "stopType": "never",
  "stopDate": null,
  "stopNumber": 1
}
```
""")

    return json_path
