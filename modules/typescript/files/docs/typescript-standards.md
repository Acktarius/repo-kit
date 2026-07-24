# TypeScript / Node standards

## Tooling

- **Biome** (`.biome.json`) for format and lint
- **TypeScript** (`tsconfig.json`) with `strict` and `tsc --noEmit`
- **`.npmrc`** holds package-manager policy — replace the placeholder before broad reuse
- **`.gitattributes`** keeps text files LF-normalized

## Expected scripts

Add these to `package.json` (adjust if the package manager differs):

```json
{
  "scripts": {
    "lint": "biome check .",
    "format": "biome format --write .",
    "typecheck": "tsc --noEmit",
    "test": "echo \"TODO: add tests\""
  }
}
```

## Cursor

Use the `package-preferences` command/skill when changing dependencies or tooling.
