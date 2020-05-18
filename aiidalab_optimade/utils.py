import re
from typing import Tuple, List, Union, Iterable
from urllib.parse import urlencode

try:
    import simplejson as json
except (ImportError, ModuleNotFoundError):
    import json

from json import JSONDecodeError

import requests

from optimade.models import ProviderResource

from aiidalab_optimade.exceptions import (
    ApiVersionError,
    InputError,
)
from aiidalab_optimade.logger import LOGGER


# Supported OPTIMADE spec version
__optimade_version__ = "0.10.1"

TIMEOUT_SECONDS = 10  # Seconds before URL query timeout is raised

PROVIDERS_URL = "https://providers.optimade.org/v1"


def perform_optimade_query(  # pylint: disable=too-many-arguments,too-many-branches
    base_url: str,
    endpoint: str = None,
    filter: Union[dict, str] = None,  # pylint: disable=redefined-builtin
    sort: str = None,
    response_format: str = None,
    response_fields: str = None,
    email_address: str = None,
    page_limit: int = None,
    page_offset: int = None,
) -> dict:
    """Perform query of database"""
    queries = {}

    if endpoint is None:
        endpoint = "/structures"
    else:
        # Make sure we supply the correct slashed format no matter the input
        endpoint = f"/{endpoint.strip('/')}"

    url_path = (
        base_url + endpoint[1:] if base_url.endswith("/") else base_url + endpoint
    )

    if filter is not None:
        if isinstance(filter, dict):
            pass
        elif isinstance(filter, str):
            queries["filter"] = filter
        else:
            raise TypeError("'filter' must be either a dict or a str")

    if sort is not None:
        queries["sort"] = sort

    if response_format is None:
        response_format = "json"
    queries["response_format"] = response_format

    if response_fields is not None:
        queries["response_fields"] = response_fields

    if email_address is not None:
        queries["email_address"] = email_address

    if page_limit is not None:
        queries["page_limit"] = page_limit

    if page_offset is not None:
        queries["page_offset"] = page_offset

    # Make query - get data
    url_query = urlencode(queries)
    complete_url = f"{url_path}?{url_query}"
    LOGGER.debug("Performing OPTIMADE query:\n%s", complete_url)
    try:
        response = requests.get(complete_url, timeout=TIMEOUT_SECONDS)
    except (
        requests.exceptions.ConnectTimeout,
        requests.exceptions.ConnectionError,
    ) as exc:
        return {
            "errors": {
                "msg": "CLIENT: Connection error or timeout.",
                "url": complete_url,
                "Exception": repr(exc),
            }
        }

    try:
        response = response.json()
    except JSONDecodeError:
        return {"errors": "CLIENT: Cannot decode response to JSON format."}

    return response


def fetch_providers(providers_url: str = None) -> list:
    """ Fetch OPTIMADE database providers (from Materials-Consortia)

    :param providers_url: String with versioned base URL to Materials-Consortia providers database
    """
    if providers_url and not isinstance(providers_url, str):
        raise TypeError("providers_url must be a string")

    if not providers_url:
        providers_url = PROVIDERS_URL

    providers = perform_optimade_query(base_url=providers_url, endpoint="/links")
    if handle_errors(providers):
        return []

    return providers.get("data", [])


_VERSION_PARTS = [
    f"/v{__optimade_version__.split('.')[0]}",  # major
    f"/v{'.'.join(__optimade_version__.split('.')[:2])}",  # minor
    f"/v{__optimade_version__}",  # patch
]


def get_versioned_base_url(base_url: str) -> str:
    """Retrieve the versioned base URL
    First, check if the given base URL is already a versioned base URL.
    Then try to going through valid version extensions to the URL.
    """
    for version in _VERSION_PARTS:
        if version in base_url:
            if re.match(fr".+{version}$", base_url):
                return base_url
            if re.match(fr".+{version}/$", base_url):
                return base_url[:-1]
            LOGGER.debug(
                "Found version '%s' in base URL '%s', but not at the end of it.",
                version,
                base_url,
            )
            return ""

    for version in _VERSION_PARTS:
        timeout_seconds = 5
        versioned_base_url = (
            base_url + version[1:] if base_url.endswith("/") else base_url + version
        )
        try:
            response = requests.get(
                f"{versioned_base_url}/info", timeout=timeout_seconds
            )
        except (
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ConnectionError,
        ):
            continue
        else:
            if response.status_code == 200:
                return versioned_base_url

    return ""


def get_list_of_valid_providers() -> List[Tuple[str, dict]]:
    """ Get curated list of database providers

    Return formatted list of tuples to use with a dropdown-widget.
    """
    providers = fetch_providers()
    res = []

    for entry in providers:
        provider = ProviderResource(**entry)

        # Skip if "exmpl"
        if provider.id == "exmpl":
            LOGGER.debug("Skipping example provider.")
            continue

        attributes = provider.attributes

        # Skip if there is no base URL
        if attributes.base_url is None:
            LOGGER.debug("Base URL found to be None for provider: %s", str(provider))
            continue

        versioned_base_url = get_versioned_base_url(attributes.base_url)
        if versioned_base_url:
            attributes.base_url = versioned_base_url
        else:
            # Not a valid/supported provider: skip
            LOGGER.debug(
                "Could not determine versioned base URL for provider: %s", str(provider)
            )
            continue

        res.append((attributes.name, attributes))

    return res


def validate_api_version(version: str, raise_on_fail: bool = True) -> str:
    """Given an OPTIMADE API version, validate it against current supported API version"""
    if not version:
        msg = f"No version found in response. Should have been v{__optimade_version__}"
        if raise_on_fail:
            raise ApiVersionError(msg)
        return msg

    if version.startswith("v"):
        version = version[1:]

    if version != __optimade_version__:
        msg = (
            f"Only OPTIMADE v{__optimade_version__} is supported. "
            f"Chosen implementation has v{version}"
        )
        if raise_on_fail:
            raise ApiVersionError(msg)
        return msg

    return ""


def get_structures_schema(base_url: str) -> dict:
    """Retrieve provider's /structures endpoint schema"""
    result = {}

    endpoint = "/info/structures"
    url_path = (
        base_url + endpoint[1:] if base_url.endswith("/") else base_url + endpoint
    )

    try:
        response = requests.get(url_path, timeout=TIMEOUT_SECONDS)
    except (
        requests.exceptions.ConnectTimeout,
        requests.exceptions.ConnectionError,
    ) as exc:
        return {
            "errors": {
                "msg": "CLIENT: Connection error or timeout.",
                "url": url_path,
                "Exception": repr(exc),
            }
        }
    else:
        if response.status_code != 200:
            return {
                "errors": {
                    "msg": "CLIENT: Not a successful 200 response.",
                    "url": url_path,
                    "status": response.status_code,
                }
            }

        properties = response.get("data", {}).get("properties", {})
        output_fields_by_json = response.get("output_fields_by_format", {}).get(
            "json", []
        )
        for field in output_fields_by_json:
            if field in properties:
                result[field] = properties[field]

        return result


def handle_errors(response: dict) -> str:
    """Handle any errors"""
    if "data" not in response and "errors" not in response:
        raise InputError(f"No data and no errors reported in response: {response}")

    if "errors" in response:
        if "data" in response:
            msg = (
                '<font color="red">Error(s) during querying,</font> but '
                f"<strong>{len(response['data'])}</strong> structures found."
            )
        else:
            msg = (
                '<font color="red">Error during querying, '
                "please try again later.</font>"
            )
        LOGGER.debug("Errored response:\n%s", json.dumps(response, indent=2))
        return msg

    return ""


def check_entry_properties(
    base_url: str,
    entry_endpoint: str,
    properties: Union[str, Iterable[str]],
    checks: Union[str, Iterable[str]],
) -> List[str]:
    """Check an entry-endpoint's properties

    :param checks: An iterable, which only recognizes the following str entries:
    "sort", "sortable", "present", "queryable"
    The first two and latter two represent the same thing, i.e., whether a property is sortable
    and whether a property is present in the entry-endpoint's resource's attributes, respsectively.
    :param properties: Can be either a list or not of properties to check.
    :param entry_endpoint: A valid entry-endpoint for the OPTIMADE implementation,
    e.g., "structures", "_exmpl_calculations", or "/extensions/structures".
    """
    if isinstance(properties, str):
        properties = [properties]
    properties = list(properties)

    if not checks:
        # Don't make any queries if called improperly (with empty iterable for `checks`)
        return properties

    if isinstance(checks, str):
        checks = [checks]
    checks = set(checks)
    if "queryable" in checks:
        checks.update({"present"})
        checks.remove("queryable")
    if "sortable" in checks:
        checks.update({"sort"})
        checks.remove("sortable")

    query_params = {
        "endpoint": f"/info/{entry_endpoint.strip('/')}",
        "base_url": base_url,
    }

    response = perform_optimade_query(**query_params)
    if handle_errors(response):
        LOGGER.error(
            "Could not retrieve information about entry-endpoint %r.\n  Message: %r\n  Response:"
            "\n%s",
            entry_endpoint,
            handle_errors(response),
            response,
        )
        if "present" in checks:
            return []
        return properties

    res = list(properties)  # Copy of input list of properties

    found_properties = response.get("data", {}).get("properties", {})
    for field in properties:
        field_property = found_properties.get(field, None)
        if field_property is None:
            LOGGER.debug(
                "Could not find %r in %r for provider with base URL %r. Found properties:\n%s",
                field,
                query_params["endpoint"],
                base_url,
                json.dumps(found_properties),
            )
            if "present" in checks:
                res.remove(field)
        elif "sort" in checks:
            sortable = field_property.get("sortable", False)
            if not sortable:
                res.remove(field)
    return res
