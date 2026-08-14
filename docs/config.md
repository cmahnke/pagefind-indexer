# Pagefind Indexer: Configuration Guide

This document provides a comprehensive guide to configuring the **Pagefind Indexer**. This tool scans a directory of HTML files, enriches them with metadata (via CSS selectors and Python functions like Wikidata queries), and builds a search index using Pagefind.

The configuration file can be written in **YAML** or **JSON**. The examples below use YAML.

---

## Top-Level Structure

The configuration file consists of three main sections:

| Section | Description |
| :--- | :--- |
| `files` | Defines source directories, output paths, and file inclusion/exclusion patterns. |
| `content` | Defines rules to exclude files based on their raw text content (e.g., redirect pages). |
| `index` | The core mapping of CSS selectors to Pagefind attributes (`meta`, `filter`, `weight`, etc.) and enrichment functions. |

---

## The `files` Section

Controls which files are processed and where the resulting index is saved.

```yaml
files:
  source: docs                   # Directory containing HTML files
  output: docs/index             # Output directory for the Pagefind index
  include:                       # Glob patterns for files to process
    - '**/*.htm'
    - '**/*.html'
  exclude:                       # Glob patterns for files/directories to ignore
    - 'tags/**'
    - 'search/**'
    - '404.html'
```

*   **`source`**: (String) The root directory to scan. Can also be passed via the `--source` CLI argument.
*   **`output`**: (String) Where the `pagefind` index files will be written. Defaults to `<source>/pagefind`.
*   **`include`**: (List of Strings) Glob patterns for files to include. Defaults to `["**/*.htm", "**/*.html"]`.
*   **`exclude`**: (List of Strings) Glob patterns for paths to exclude from indexing.

## The `content` Section

Allows you to skip files based on their raw HTML content using Regular Expressions. This is useful for skipping redirect pages or placeholder files.

```yaml
content:
  ignore:
    - "<meta http-equiv=\"refresh\" content=\"0; url="
```

*   **`ignore`**: (List of Strings) Regex patterns. If *any* pattern matches the file's raw content, the file is excluded from the index.

## The `index` Section

This is the core of the configuration. It maps CSS selectors to Pagefind data attributes (`data-pagefind-*`).

### Basic Pagefind Attributes

These keys configure how Pagefind weights and structures the document body.

| Key | Pagefind Attribute | Syntax | Description |
| :--- | :--- | :--- | :--- |
| `body` | `data-pagefind-body` | List of Strings | Defines the main content area. Only text inside these selectors is indexed. |
| `ignore` | `data-pagefind-ignore` | List of Strings/Dicts | Elements to exclude from indexing. Use `"all"` to ignore the element and its children. |
| `weight` | `data-pagefind-weight` | List of Dicts | Assigns a numerical weight to elements (e.g., Headings). |
| `index-attrs`| `data-pagefind-index-attrs`| List of Dicts | Tells Pagefind to index specific HTML attributes alongside text. |

**Example:**
```yaml
index:
  body:
    - .content-container
  ignore:
    - header.header
    - footer.footer: all    # Ignores footer and all children
    - script: all
  weight:
    - "h1": 7.0
    - "h2": 6.0
  index-attrs:
    - a: "[data-wikidata-entity]" # Indexes the value of this attribute
```

### Metadata, Filters, and Sorting

These keys define fields that can be used for filtering, sorting, and displaying metadata in search results.

**Structure:**
The value must be a **dictionary** where the keys are your custom field names (e.g., `author`, `date`, `tag`), and the values are lists of **Selector Definitions**.

```yaml
index:
  meta:
    author: 'meta[name="author"]'
  filter:
    tag:
      - ".meta .tags a":
          function: extract
          args: { pattern: "s/#(.*)/$1/g" }
  sort:
    date:
      - ".date time": "[datetime]"
```

---

## Selector Syntax Reference

When defining how to extract data for `meta`, `filter`, `sort`, `weight`, etc., you can use three different formats:

### Simple String (Text Extraction)
Matches the CSS selector and extracts the **text content** of the element.
```yaml
author: 'meta[name="author"]'
# Note: For meta tags, you usually want the 'content' attribute, see format B.
```

### Dictionary (Attribute Extraction)
Matches the CSS selector (key) and extracts a specific **HTML attribute** (value in brackets).
```yaml
date:
  - ".date time": "[datetime]"   # Extracts datetime="2023-01-01"
image:
  - "figure img": "[src]"        # Extracts src="/image.jpg"
```

### Dictionary (Function Execution)
Matches the CSS selector (key) and passes the DOM node to a **Python function** to generate a complex value.
```yaml
variants:
  - "a[data-wikidata-entity]":
      function: variants
      args:
        lang: "{lang}"
```
*(See Section 6 for available functions and arguments).*

---

## Built-in Enrichment Functions

You can call these Python functions within your Selector Definitions (Format C) to dynamically enrich your index.

### `extract`
Extracts text or an attribute and optionally applies a regex replacement.
*   **`attribute`**: (Optional) HTML attribute to extract. Defaults to text content.
*   **`pattern`**: (Optional) A `sed`-style regex replacement pattern (e.g., `"s/search/replace/g"`).
*   **`ignore_unchanged`**: (Optional, Boolean) If `true` and the regex pattern doesn't match/replace anything, returns an empty string. Highly recommended for `filter` fields to prevent empty filter options.

```yaml
section:
  - body:
      function: extract
      args:
        attribute: "class"
        pattern: "s/.*section-(.[^ ]*).*/$1/g"
        ignore_unchanged: true
```

### `type` (Wikidata)
Queries Wikidata to find the broad "base type" category of an entity (e.g., "Human", "Organization", "Book", "City").
*   **`attribute`**: (Optional) The HTML attribute containing the Wikidata QID. Defaults to `data-wikidata-entity`.
*   **`lang`**: (Optional) Language code for the label. Defaults to `en`.

### `variants` (Wikidata)
Queries Wikidata to get alternative labels (aliases/synonyms) for an entity QID. This drastically improves search recall.
*   **`attribute`**: (Optional) HTML attribute containing the QID. Defaults to `data-wikidata-entity`.
*   **`lang`**: (Optional) Language code for the labels. Defaults to `en`.

### `generate_css_selector`
Generates a unique, highly specific CSS selector string for the matched DOM node. Useful if you want to map search results back to specific UI components.
*   *No arguments required.*

## Context Variables

Function arguments support string interpolation using the context of the current HTML file.

*   **`{lang}`**: Automatically extracts the `lang` attribute from the `<html lang="...">` tag. If missing, it defaults to `de` (as defined in the script's `DEFAULT_LANG`).

```yaml
args:
  lang: "{lang}" # Dynamically passes "en", "fr", "de" etc. to the Wikidata functions
```

## Complete Example Configuration

```yaml
files:
  output: docs/index
  source: docs
  include:
    - '**/*.htm'
    - '**/*.html'
  exclude:
    - 'tags/**'
    - 'search/**'
    - '404.html'
    - 'post/**/article.html'

content:
  ignore:
    - "<meta http-equiv=\"refresh\" content=\"0; url="

index:
  # 1. Body & Ignoring
  body:
    - .content-container
  ignore:
    - header.header
    - footer.footer: all
    - script: all
    - "div.menu": all

  # 2. Weighting
  weight:
    - "h1": 7.0
    - "h2": 6.0
    - "h3": 5.0
    - "a[data-wikidata-entity]": 5.0 # Boost Wikidata entities

  # 3. Metadata Extraction
  meta:
    author: 'meta[name="author"]'
    title:
      - h1.post-title
      - ".section-head h1.section-head-title"
    date:
      - ".date time": "[datetime]"
    image:
      - ".gallery .gallery-image.caption": "[href]"
      - "figure img": "[src]"
    selector:
      - "p, h1, h2":
          function: generate_css_selector

  # 4. Sorting
  sort:
    date:
      - ".date time": "[datetime]"

  # 5. Filtering & Enrichment (Wikidata & Regex)
  filter:
    type:
      - "a[data-wikidata-entity]":
          function: type
          args:
            lang: "{lang}"
    tag:
      - ".meta .tags a":
          function: extract
          args:
            pattern: "s/#(.*)/$1/g"
    section:
      - body:
          function: extract
          args:
            attribute: "class"
            pattern: "s/.*section-(.[^ ]*).*/$1/g"
            ignore_unchanged: true
    variants:
      - "a[data-wikidata-entity]":
          function: variants
          args:
            lang: "{lang}"

  # 6. Attribute Indexing
  index-attrs:
    - a: "[data-wikidata-entity]"
```
