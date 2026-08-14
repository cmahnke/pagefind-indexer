# Pagefind Indexer: CLI Arguments

While most configuration lives in the YAML/JSON file, the script accepts the following Command Line arguments which override or supplement the config:

| Argument | Description | Default |
| :--- | :--- | :--- |
| `-c, --config` | **Required.** Path to the configuration file. | None |
| `-s, --source` | Source directory (Overrides `files.source`). | Config value |
| `-o, --output` | Output directory (Overrides `files.output`). | `<source>/pagefind` |
| `-l, --limit` | **Max Wikidata API requests per second.** Prevents IP bans. | `1` |
| `-d, --debug` | Enables verbose DEBUG logging. | `False` |
