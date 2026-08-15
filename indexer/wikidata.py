import json
import logging
import requests
from requests_ratelimiter import LimiterSession

log = logging.getLogger(__name__)

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIDATA_HEADERS = {
    "Accept": "application/sparql-results+json",
    "User-Agent": "PagefindExperimentalEnrich/0.0.1 (https://christianmahnke.de/) requests-python",
}

wikidata_cache = {}
# Initialize with a default rate limit, can be overridden from the main script
session = LimiterSession(per_second=1)


def set_rate_limit(per_second):
    """Re-initialize the LimiterSession with a custom rate limit."""
    global session
    session = LimiterSession(per_second=per_second)


def get_labels(qid, lang):
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
        response = session.get(WIKIDATA_ENDPOINT, params={"query": query}, headers=WIKIDATA_HEADERS)
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


def get_base_type(qid, lang="en", default_label=None):
    if qid in wikidata_cache:
        if lang in wikidata_cache[qid] and "base_type" in wikidata_cache[qid][lang]:
            return wikidata_cache[qid][lang]["base_type"]
        else:
            wikidata_cache[qid][lang] = {}
    else:
        wikidata_cache[qid] = {}
        wikidata_cache[qid][lang] = {}

    predefined_base_qids = [
        "Q5",  # Human (Person)
        "Q729",  # Animal
        "Q43229",  # Organization (Company, NGO, Government agency, etc.)
        "Q14897293",  # Fictional entity
        "Q16566827",  # Building (Structure, architectural work)
        "Q7397",  # Software
        "Q39670",  # Computer hardware
        "Q11446",  # Ship
        "Q11439",  # Aircraft (Plane, helicopter, etc.)
        "Q867018",  # Handicraft
        "Q11424",  # Film (Movie)
        "Q3305213",  # Painting
        "Q2431196",  # Musical work (Song, symphony, etc.)
        "Q1107",  # Sculpture
        "Q4985654",  # Video game
        "Q12645",  # Photograph
        "Q47461344",  # Literary work (Books, poems, etc.)
        "Q838948",  # Work of art (Broader than specific arts like Painting, Sculpture)
        "Q47154546",  # Creative work (Very broad, encompasses all artistic/literary works)
        "Q6671777",  # Structure
        "Q618123",  # Geographical feature (Mountain, river, lake, etc.)
        "Q56061",  # Geographic location (Place / Location - broader than geographical feature)
        "Q2695280",  # Technique (Specific procedure/skill, e.g., surgical technique)
        "Q1182586",  # Method (Systematic procedure, technique)
        "Q1190554",  # Event (Historical event, sports event, festival, etc.)
        "Q712534",  # Natural phenomenon (Earthquake, volcano, weather event)
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
        response = session.get(WIKIDATA_ENDPOINT, headers=WIKIDATA_HEADERS, params={"query": sparql_query})
        response.raise_for_status()
        data = response.json()

        results = data.get("results", {}).get("bindings", [])

        if results:
            base_class_info = results[0]
            base_class_qid = base_class_info["baseClass"]["value"].split("/")[-1]
            base_class_label = base_class_info["baseClassLabel"]["value"]

            if default_label is not None and base_class_label == "":
                base_class_label = default_label

            wikidata_cache[qid][lang]["base_type"] = {
                "qid": base_class_qid,
                "label": base_class_label,
            }
            return wikidata_cache[qid][lang]["base_type"]

        else:
            return None  # No base class found from the predefined list

    except requests.exceptions.RequestException as e:
        print(f"Error making request to Wikidata for QID {qid}: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response from Wikidata for QID {qid}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred for QID {qid}: {e}")
        return None


# Callable index enrichment functions
def type(node, attribute="data-wikidata-entity", lang="en"):
    if attribute is None:
        qid = node.text
    else:
        qid = node[attribute]
    base = get_base_type(qid, lang)
    if base is not None:
        return base["label"]
    log.info(f"Couldn't find base type of {qid}")
    return ""


def variants(node, attribute="data-wikidata-entity", lang="en"):
    if attribute is None:
        qid = node.text
    else:
        qid = node[attribute]
    return get_labels(qid, lang)
