import asyncio
import json
import yaml
import logging
import os
import sys
import re
import argparse
import pathlib
import requests
from requests_ratelimiter import LimiterSession
from pagefind.index import PagefindIndex, IndexConfig
from bs4.element import Tag
from bs4 import BeautifulSoup
import difflib

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger(__name__)

default_include = ["**/*.htm", "**/*.html"]
data_attribute_prefix = "data-pagefind-"
DEFAULT_LANG = "de"
WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIDATA_HEADERS = {
    "Accept": "application/sparql-results+json",
    "User-Agent": "PagefindExperimentalEnrich/0.0.1 (https://christianmahnke.de/) requests-python"
}

wikidata_cache = {}

class Page:
    def __init__(self, relative_path, filepath, content = None):
        self.relative_path= relative_path
        self.filepath = filepath
        if isinstance(content, list):
            self.contents = content
        else:
            self.contents = [content]

    def first(self):
        return self.contents[0]


## Helper functions for index enrichment

def get_labels (qid, lang):
    if qid in wikidata_cache:
        if lang in wikidata_cache[qid] and "labels" in wikidata_cache[qid][lang]:
            return wikidata_cache[qid][lang]["labels"]
        else:
            wikidata_cache[qid][lang] = {}
    else:
        wikidata_cache[qid] = {}
        wikidata_cache[qid][lang] = {}

    uri = f"http://www.wikidata.org/entity/{qid}"
    query = f"""
    SELECT DISTINCT ?altLabel
    WHERE {{
      VALUES ?object {{ <{uri}> }}

      OPTIONAL {{
        ?object <http://www.w3.org/2000/01/rdf-schema#label> ?label .
        FILTER (lang(?label) = "{lang}")
      }}

      {{
        ?object <http://www.w3.org/2004/02/skos/core#altLabel> ?altLabel .
        FILTER (lang(?altLabel) = "{lang}" || lang(?altLabel) = "")
      }}
      UNION
      {{
        ?object <http://www.w3.org/2004/02/skos/core#altLabel> ?altLabel .
        FILTER (!langMatches(lang(?altLabel), "*"))
      }}
    }}
    """

    try:
        log.debug(f"Querying Wikidata for labels of {qid} in language '{lang}'")
        response = requests.get(WIKIDATA_ENDPOINT, params={"query": query}, headers=WIKIDATA_HEADERS)
        response.raise_for_status()

        data = response.json()
        alt_labels = []
        for binding in data["results"]["bindings"]:
            if "altLabel" in binding:
                alt_labels.append(binding["altLabel"]["value"])

        wikidata_cache[qid][lang]["labels"] = ";".join(alt_labels)
        return wikidata_cache[qid][lang]["labels"]

    except requests.exceptions.RequestException as e:
        print(f"Error querying Wikidata: {e}")
        return ""
    except json.JSONDecodeError:
        print("Error decoding JSON response from Wikidata.")
        return ""
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return ""


def get_base_type(qid, lang = 'en', default_label = None):
    if qid in wikidata_cache:
        if lang in wikidata_cache[qid] and "base_type" in wikidata_cache[qid][lang]:
            return wikidata_cache[qid][lang]["base_type"]
        else:
            wikidata_cache[qid][lang] = {}
    else:
        wikidata_cache[qid] = {}
        wikidata_cache[qid][lang] = {}

    predefined_base_qids = [
        'Q5',          # Human (Person)
        'Q729',        # Animal
        'Q43229',      # Organization (Company, NGO, Government agency, etc.)
        'Q14897293',   # Fictional entity
        'Q16566827',   # Building (Structure, architectural work)
        'Q7397',       # Software
        'Q39670',      # Computer hardware
        'Q11446',      # Ship
        'Q11439',      # Aircraft (Plane, helicopter, etc.)
        'Q867018',     # Handicraft
        'Q11424',      # Film (Movie)
        'Q3305213',    # Painting
        'Q2431196',    # Musical work (Song, symphony, etc.)
        'Q1107',       # Sculpture
        'Q4985654',    # Video game
        'Q12645',      # Photograph
        'Q47461344',   # Literary work (Books, poems, etc.)
        'Q838948',     # Work of art (Broader than specific arts like Painting, Sculpture)
        'Q47154546',   # Creative work (Very broad, encompasses all artistic/literary works)
        'Q6671777',    # Structure

        'Q618123',     # Geographical feature (Mountain, river, lake, etc.)
        'Q56061',      # Geographic location (Place / Location - broader than geographical feature)
        'Q2695280',    # Technique (Specific procedure/skill, e.g., surgical technique)
        'Q1182586',    # Method (Systematic procedure, technique)
        'Q1190554',    # Event (Historical event, sports event, festival, etc.)
        'Q712534',     # Natural phenomenon (Earthquake, volcano, weather event)
        #'Q151885',     # Concept (Abstract ideas - use with caution, can be very broad)
    ]

    values_clause = " ".join([f"wd:{q}" for q in predefined_base_qids])

    sparql_query = f"""
    SELECT ?baseClass ?baseClassLabel ?directClass ?directClassLabel WHERE {{
      VALUES ?targetItem {{ wd:{qid} }}

      ?targetItem wdt:P31 ?directClass.
      ?targetItem wdt:P31/wdt:P279* ?baseClass.

      VALUES ?baseClassInList {{ {values_clause} }}
      FILTER (?baseClass = ?baseClassInList)

      SERVICE wikibase:label {{
        bd:serviceParam wikibase:language "{lang},en".
        ?baseClass rdfs:label ?baseClassLabel.
        ?directClass rdfs:label ?directClassLabel.
      }}
    }}
    LIMIT 1
    """

    try:
        response = session.get(WIKIDATA_ENDPOINT, headers=WIKIDATA_HEADERS, params={'query': sparql_query})
        response.raise_for_status()
        data = response.json()

        results = data.get('results', {}).get('bindings', [])

        if results:
            base_class_info = results[0]
            base_class_qid = base_class_info['baseClass']['value'].split('/')[-1]
            base_class_label = base_class_info['baseClassLabel']['value']

            if default_label is not None and base_class_label == "":
                base_class_label = default_label

            wikidata_cache[qid][lang]["base_type"] = {'qid': base_class_qid, 'label': base_class_label}
            return wikidata_cache[qid][lang]["base_type"]

        else:
            return None # No base class found from the predefined list

    except requests.exceptions.RequestException as e:
        print(f"Error making request to Wikidata for QID {qid}: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response from Wikidata for QID {qid}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred for QID {qid}: {e}")
        return None

# See https://searchfox.org/mozilla-central/source/devtools/shared/inspector/css-logic.js arround line 634
def generate_css_selector(node):
    def escape(selector):
        numeric_pattern = r"^(\d+).*$"
        if re.match(numeric_pattern, selector):
            selector = re.sub(numeric_pattern, lambda m: "".join(list(map(lambda c: "\\" + str(ord(c)), list(m.group(1))))), selector)
        for k, v in [(".", "\\."), (":", "\\:")]:
            selector = selector.replace(k, v)
        return selector

    if not isinstance(node, Tag):
        return None

    ancestors = node.find_parents()
    path_nodes = []
    for ancestor in reversed(ancestors):
        if ancestor.name != '[document]':
            path_nodes.append(ancestor)
    path_nodes.append(node)

    selector_parts: List[str] = []

    for i, current_node in enumerate(path_nodes):
        if not isinstance(current_node, Tag):
            continue

        part = current_node.name

        if current_node.has_attr('id') and current_node['id']:
            id = escape(current_node['id'])
            part += f"#{id}"
        elif current_node.has_attr('class') and current_node['class']:
            classes = list(map(lambda e: escape(e), current_node['class']))
            part += '.' + '.'.join(classes)

        if current_node.parent and current_node.name != 'html':
            siblings_of_same_type = [
                s for s in current_node.parent.children
                if isinstance(s, Tag) and s.name == current_node.name
            ]
            if len(siblings_of_same_type) > 1:
                try:
                    nth_index = siblings_of_same_type.index(current_node) + 1
                    part += f":nth-of-type({nth_index})"
                except ValueError:
                    pass
        selector_parts.append(part)

    full_selector = " > ".join(selector_parts)

    root_document = node.find_parent(None)
    if root_document:
        found_elements = root_document.select(full_selector)
        if len(found_elements) == 1 and found_elements[0] is node:
            return full_selector
        elif len(found_elements) > 1:
            return None
        else:
            return None
    return None

def sed_style_replace(string, pattern):
    if not (pattern.startswith('s') and len(pattern) >= 6 and pattern.endswith('g')):
        raise Exception(f"Malformed {pattern}")
    sep = pattern[1]
    if pattern.count(sep) != 3:
        raise Exception(f"Not a valid pattern {pattern}")
    search, _, rest = pattern[2:].partition(sep)
    replace, _, rest = rest.partition(sep)
    if not search or rest != 'g':
        raise Exception(f"Not a valid pattern {pattern}")
    replace = replace.replace("$", "\\")
    return re.sub(search, replace, string, count=0, flags=re.MULTILINE)

# Callable index enrichment functions

def extract(node, attribute = None, pattern = None, ignore_unchanged = False):
    if attribute is None:
        text = node.text
    elif attribute in node:
        text = node[attribute]
    else:
        log.warning(f"Atribute {attribute} not set on {node.name}")
        text  = ""
    # BeautifulSoup implements the magic by default antipattern: class attributes are returned as list without providing symetric way to work around this.
    # Like an accesor without parsing. There is a genral setting `multi_valued_attributes=None`
    if isinstance(text, list):
        text = " ".join(text)

    if pattern is not None:
        replaced_text = sed_style_replace(text, pattern)
        if text == replaced_text and ignore_unchanged:
            replaced_text = ""
    else:
        replaced_text = text
    log.debug(f"Extracting node, attribute {attribute}, pattern {pattern}, result: '{text}'")
    return replaced_text

def type(node, attribute="data-wikidata-entity", lang = "en"):
    if attribute is None:
        qid = node.text
    else:
        qid = node[attribute]
    base = get_base_type(qid, lang)
    if base is not None:
        return base["label"]
    log.info(f"Couldn't find base type of {qid}")
    return ""

def variants(node, attribute="data-wikidata-entity", lang = "en"):
    if attribute is None:
        qid = node.text
    else:
        qid = node[attribute]
    return get_labels(qid, lang)

def load_config(config_file):
    _, ext = os.path.splitext(config_file)
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            if ext.lower() in ['.json', '.jsonc']:
                config = json.load(f)
            elif ext.lower() in ['.yaml', '.yml']:
                config = yaml.safe_load(f)
            else:
                print(f"Error: Configuration file '{config_file}' must be JSON or YAML.")
                return
            return config
    except FileNotFoundError:
        print(f"Error: Configuration file '{config_file}' not found.")
        return
    except (json.JSONDecodeError, yaml.YAMLError) as e:
        print(f"Error parsing configuration file '{config_file}': {e}")
        return

def create_file_list(source_dir, include, exclude = None, ignore = None):
    patterns = []
    if ignore is not None:
        if isinstance(ignore, str):
            ignore = [ignore]
        for i in ignore:
            patterns.append(re.compile(i))
    index_files = {}
    for root, _, files in os.walk(source_dir):
        for file in files:
            index = False
            filepath = os.path.join(root, file)
            relative_path = os.path.relpath(filepath, source_dir)
            for incl in include:
                if pathlib.PurePath(relative_path).match(incl):
                    index = True
                    break
            if not index:
                continue
            if exclude is not None:
                for excl in exclude:
                    if pathlib.PurePath(relative_path).full_match(excl):
                        log.debug(f"Excluding {relative_path} (Pattern '{excl}')")
                        index = False
                        break
            if not index:
                continue
            if patterns:
                with open(filepath, 'r', encoding='utf-8') as f:
                    contents = f.read()
                    for pattern in patterns:
                        if pattern.search(contents):
                            log.debug(f"Excluding {relative_path} based on content {pattern.pattern}")
                            index = False
                            break

            if index:
                log.debug(f"Including {relative_path}")
                index_files[relative_path] = filepath

    return index_files

def preprocess_html_file(filepath, config):
    def expand_args(args, ctx):
        if isinstance(args, dict):
            return dict(map(lambda i: (i[0], i[1].format(**ctx)) , args.items()))
        elif isinstance(args, list):
            return list(map(lambda e: e.format(**ctx), args))
        else:
            return args.format(**ctx)

    def add_meta(element, attr = "meta", field = "", field_def = None, ctx=None, skip_empty = False):
        #if (any(map(content.__contains__, [",", "'", "\""]))):
        #    log.warning(f"Unknown selector definition type for '{key}': {type(selectors_def)}. Skipping.")
        if isinstance(field_def, dict):
            value_def = list(field_def.values())[0]
            if isinstance(value_def, dict):
                additional_attr = f"{data_attribute_prefix}{attr}-{field}"
                if (additional_attr in element):
                    raise Exception("Attribute {additional_attr} already exists!")
                if "function" in value_def:
                    if "args" in value_def:
                        if ctx is not None:
                            args = expand_args(value_def["args"], ctx)
                        else:
                            args = value_def["args"]
                        if "args" in value_def and isinstance(args, dict):
                            function_result = globals()[value_def["function"]](element, **args)
                        elif "args" in value_def and isinstance(args, list):
                            function_result = globals()[value_def["function"]](element, *args)
                        else:
                            function_result = globals()[value_def["function"]](element, args)
                        log.debug(f"Called {value_def["function"]} with args {args}")
                    else:
                        function_result = globals()[value_def["function"]](element)

                    if skip_empty and function_result == "":
                        log.debug(f"Skipping empty result for attribute '{attr}' (target '{additional_attr}'), field '{field}', call '{value_def}'")
                    else:
                        log.debug(f"Got result for attribute '{attr}' (target '{additional_attr}'), field '{field}', call '{value_def}':\n{function_result}")
                        element[additional_attr] = function_result
                        attr_val = f"{field}[{additional_attr}]"
                else:
                    log.warning(f"Unsupported dict value definition {value_def} ")
            else:
                attr_val = field + value_def
        else:
            attr_val = field
        target_attr = data_attribute_prefix + attr
        if element.has_attr(target_attr):
            value = f"{element[target_attr]}, {attr_val}"
            element[target_attr] = value
            log.debug(f"Updated attribute '{target_attr}' with value '{value}'")
        else:
            try:
                element[target_attr] = attr_val
                log.debug(f"Added attribute '{target_attr}' with value '{attr_val}'")
            except NameError:
                log.debug(f"Ignoring unset value for {attr}")
                pass

    def add_attr(element, attr, field_def):
        if isinstance(field_def, str):
            element[data_attribute_prefix + attr] = ""
        elif isinstance(field_def, dict):
            value_def = list(field_def.values())[0]
            if isinstance(value_def, dict):
                # TODO: Largely untested
                if "function" in value_def:
                    if "args" in value_def and isinstance(value_def["args"], dict):
                        attr_val = globals()[value_def["function"]](element, **value_def["args"])
                    if "args" in value_def and isinstance(value_def["args"], list):
                        attr_val = globals()[value_def["function"]](element, *value_def["args"])
                    else:
                        attr_val = globals()[value_def["function"]](element)
                else:
                    log.warning(f"Unsupported dict value definition {value_def} ")
            else:
                attr_val = value_def
            element[data_attribute_prefix + attr] = attr_val


    with open(filepath, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')
    #if logging.DEBUG >= log.level:
    #    initial_html_content = str(soup)
    lang_tag = soup.select("html[lang]")
    #if lang_tag is not None or len(lang_tag) >= 1 and "lang" in lang_tag[0]:
    try:
        lang = lang_tag[0]["lang"]
        log.info(f"Procesing {filepath}, language {lang}")
    #else:
    except (IndexError, ValueError):
        log.warning(f"Lang tag not found for {filepath}, setting to {DEFAULT_LANG}")
        lang = DEFAULT_LANG

    for key, selectors_def in config.items():
        data_attribute_key = data_attribute_prefix + key


        if isinstance(selectors_def, str):
            selectors = [selectors_def]
        elif isinstance(selectors_def, list):
            selectors = selectors_def
        elif isinstance(selectors_def, dict):

            if key in ["meta", "default-meta", "filter", "sort"]:

                for sub_key, sub_selector in selectors_def.items():
                    log.debug(f"Procesing {sub_key} with {sub_selector}")
                    if isinstance(sub_selector, str):
                        sub_selectors = [sub_selector]
                    elif isinstance(sub_selector, dict):
                        raise Exception("Wrong datatype, use list instead of dict")
                    else:
                        sub_selectors = sub_selector
                    for selector in sub_selectors:
                        if isinstance(selector, str):
                            sel = selector
                        elif isinstance(selector, dict):
                            sel = list(selector.keys())[0]
                        elements = soup.select(sel)
                        for element in elements:
                            skip_empty = False
                            if key == "filter":
                                skip_empty = True
                            add_meta(element, key, sub_key, selector, {"lang": lang}, skip_empty)
            continue
        else:
            log.warning(f"Unknown selector definition type for '{key} and dict, maybe selectors need to be given as lsit?': {type(selectors_def)}. Skipping.")
            continue

        if not isinstance(selectors_def, dict):
            log.debug(f"Procesing {key} with {selectors_def}")
            for sub_key in selectors:
                if isinstance(sub_key, str):
                    selector = sub_key
                elif isinstance(sub_key, dict):
                    selector = list(sub_key.keys())[0]
                elements = soup.select(selector)
                for element in elements:
                    if key == "body":
                        element[data_attribute_key] = ""
                    elif key in ["ignore", "weight", "index-attrs"]:
                        add_attr(element, key, sub_key)
                    else:
                        log.warning(f"Unhandled '{key}'!")
                        element[key] = ""

    modified_html_content = str(soup)
    #if logging.DEBUG >= log.level:
    #    result = difflib.unified_diff(initial_html_content, modified_html_content)
    #    diff = ''.join(map(str, result))
    #    log.debug(f"HTML after processing:\n{diff}")
    log.debug(f"HTML after processing:\n{modified_html_content}")
    return modified_html_content

async def index(contents, output_dir):
    async with PagefindIndex() as index:
        processed_files_count = 0
        for page in contents:
            relative_path = page.relative_path
            filepath = page.filepath
            content = page.first()

            try:
                await index.add_html_file(
                    url=f"/{relative_path}",
                    content=content,
                    source_path=filepath
                )
                processed_files_count += 1

            except Exception as e:
                log.error(f"Error processing file {filepath}: {e}")

        log.info(f"Processed {processed_files_count} HTML files.")

        log.info(f"Writing Pagefind index to '{output_dir}'...")
        await index.write_files(output_path=output_dir)
        log.info("Pagefind indexing complete!")

def main():
    if sys.version_info[0] < 3 or sys.version_info[1] < 13:
        raise Exception("Must be using Python 3.13")

    parser = argparse.ArgumentParser(description='Index page', add_help=False, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-s', '--source', type=pathlib.Path, help='The source directory containing HTML files to be indexed',)
    parser.add_argument('-c', '--config', type=pathlib.Path, help='File containing configuration (JSON or YAML)', required=True)
    parser.add_argument("-o", "--output", type=pathlib.Path, help="The directory where Pagefind will write its index files. Defaults to a 'pagefind' subdirectory within the source directory.")
    parser.add_argument("-l", "--limit", type=int, help="The maximum number of requests per second", default=1)
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("-h", "--help", action="store_true", help="Show help")
    args = parser.parse_args()

    if args.help:
        parser.print_help()
        sys.exit(0)

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    config = load_config(args.config)

    if config is None:
        raise Exception("Failed to load config!")

    if not "files" in config:
        raise Exception("No file section in config!")

    if ("source" in config["files"]):
        source_dir = config["files"]["source"]
    elif ("source" in args and args.source):
        source_dir = args.source

    if ("output" in config["files"]):
        output_dir = config["files"]["output"]
    elif ("output" in args and args.output):
        output_dir = args.output

    if output_dir is None:
        output_dir = os.path.join(source_dir, "pagefind")

    include = default_include
    if ("include" in config["files"]):
        include = config["files"]["include"]
    exclude = None
    if ("exclude" in config["files"]):
        exclude = config["files"]["exclude"]

    ignore = None
    if ("ignore" in config["content"]):
        ignore = config["content"]["ignore"]

    global session
    session = LimiterSession(per_second=args.limit)

    log.info(f"Starting Pagefind indexing for '{source_dir}'...")
    log.info(f"Output directory: '{output_dir}'")
    log.info(f"Using configuration from: '{args.config}'")

    file_list = create_file_list(source_dir, include, exclude, ignore)
    index_config = config["index"]
    pages = []
    for relative_path, filepath in file_list.items():
        pages.append(Page(relative_path, filepath, preprocess_html_file(filepath, index_config)))
    asyncio.run(index(pages, output_dir))

if __name__ == "__main__":
    try:
        print("Starting indexer")
        main()
    except KeyboardInterrupt:
        log.info("Indexer stopped by user (Ctrl+C).")
