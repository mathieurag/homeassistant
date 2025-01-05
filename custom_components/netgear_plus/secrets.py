"""Example of how to use the NetgearPlus library."""

import logging

import requests  # noqa: F401

import netgear_plus

logging.basicConfig(level=logging.DEBUG)


def show(data: dict, text: str = "") -> None:
    """
    Display the keys and values in the data dictionary that contain the specified text.

    Args:
        data (dict): The dictionary containing the data to display.
        text (str, optional): The text to filter the keys. Defaults to "".

    """
    max_key_length = max(len(key) for key in data)
    for key in sorted(data.keys()):
        if not text or text in key:
            print(f"{key.ljust(max_key_length)}\t{data[key]}")  # noqa: T201


def compare(data1: dict, data2: dict, text: str = "") -> None:
    """
    Compare two dicts.

    Display the keys and values from two dictionaries side by side,
    filtered by the specified text.

    Args:
        data1 (dict): The first dictionary containing the data to display.
        data2 (dict): The second dictionary containing the data to display.
        text (str, optional): The text to filter the keys. Defaults to "".

    """
    all_keys = sorted(set(data1.keys()).union(data2.keys()))
    max_key_length = max(len(key) for key in all_keys)
    max_value1_length = max(len(str(data1.get(key, "N/A"))) for key in all_keys)
    max_value2_length = max(len(str(data2.get(key, "N/A"))) for key in all_keys)

    for key in all_keys:
        if not text or text in key:
            value1 = str(data1.get(key, "N/A"))
            value2 = str(data2.get(key, "N/A"))
            print(  # noqa: T201
                f"{key.ljust(max_key_length)}\t"
                f"{value1.ljust(max_value1_length)}\t"
                f"{value2.ljust(max_value2_length)}"
            )


ip = "192.168.178.30"
pw = "hQe!$n5TxSY5W&n89B^b"
sw = netgear_plus.NetgearSwitchConnector(ip, pw)
