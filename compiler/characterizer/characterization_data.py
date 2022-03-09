"""
Saves and loads characterized data to and from file
Refer to characterization_data_test.py for sample usage
"""
import json
import os
import pathlib
import re
from copy import deepcopy
from itertools import groupby
from typing import List, Tuple, Dict, Union

from globals import OPTS

char_data_format = Dict[str, Dict[str, float]]

FLOAT_REGEX = r"[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?"


def construct_suffixes(suffixes: List[Tuple[str, float]] = None):
    if suffixes:
        return "_".join(["{}_{:.3g}".format(key, value) for key, value in suffixes])
    return ""


def construct_suffixes_regex(suffixes: List[Tuple[str, float]] = None):
    if suffixes:
        return "_".join(["{}_{}".format(key, FLOAT_REGEX) for key, value in suffixes])
    return ""


def get_data_dir():
    return os.path.join(OPTS.openram_tech, "char_data")


def get_data_file(cell_name, file_suffixes: List[Tuple[str, float]] = None):
    data_directory = get_data_dir()

    suffixes = construct_suffixes(file_suffixes)
    if suffixes:
        suffixes = "_" + suffixes

    cell_name += suffixes + ".json"
    return os.path.join(data_directory, cell_name)


def get_size_key(size: float, size_suffixes: List[Tuple[str, float]] = None):
    if size_suffixes is None:
        size_suffixes = []
    size_suffixes = deepcopy(size_suffixes)
    size_suffixes.insert(0, ("size", size))
    return construct_suffixes(size_suffixes)


def load_json_file(file_name):
    if not os.path.exists(os.path.dirname(file_name)):
        pathlib.Path(os.path.dirname(file_name)).mkdir(parents=True, exist_ok=True)

    if not os.path.exists(file_name):
        with open(file_name, "w") as data_file:
            json.dump({}, data_file)

    with open(file_name, "r") as data_file:
        return json.load(data_file)


def save_data(cell_name: str, pin_name: str, value: float,
              size: float = 1, clear_existing=False,
              file_suffixes: List[Tuple[str, float]] = None,
              size_suffixes: List[Tuple[str, float]] = None):
    """
    Save data from characterization to json
    :param cell_name: name of characterized cell
    :param pin_name: characterized pin
    :param value: value
    :param size: characterized cell size. Leave as one for cells with just one size
    :param clear_existing: Remove previous data from json. Careful!!
    :param file_suffixes: e.g. height or beta where relevant.
                         height is relevant for example inverters.
                         ("height", 1) adds _height_1 to file name.
                          No interpolation happens with file_suffixes
    :param size_suffixes: e.g. number of fingers or word_size.
                          Adds suffix to the size key similar to file_suffixes
                          Linear interpolation when size specified doesn't match
                           characterized data exactly
    :return: Updated json file content
    """
    file_name = get_data_file(cell_name, file_suffixes)
    existing_data = load_json_file(file_name)  # ensure file existence

    if clear_existing:
        existing_data = {}  # type: char_data_format

    if pin_name not in existing_data:
        existing_data[pin_name] = {}

    size_key = get_size_key(size, size_suffixes)
    existing_data[pin_name][size_key] = value

    with open(file_name, "w") as data_file:
        json.dump(existing_data, data_file, indent=2)
    return existing_data


def filter_suffixes(suffixes: List[Tuple[str, float]], candidates: List[str]):
    """

    :param suffixes: all suffixes
    :param candidates: the candidates
    :return:
    """

    while len(suffixes) > 0:
        suffix_name, suffix_value = suffixes[-1]

        suffixes = suffixes[:-1]

        search_pattern = "_{}_({})".format(suffix_name, FLOAT_REGEX)
        matches = list(filter(lambda x: re.search(search_pattern, x), candidates))
        if not matches:
            # saved data didn't specify this criteria
            continue
        # find the closest match
        candidate_values = [[x, float(re.search(search_pattern, x).group(1))]
                            for x in matches]
        closest_value = min(candidate_values, key=lambda x: abs(x[1] - suffix_value))[1]

        candidates_with_closest_value = list(filter(
            lambda x: x[1] == closest_value, candidate_values))

        candidates = [x[0] for x in candidates_with_closest_value]

    return candidates


def find_exact_matches(candidates: List[str], suffixes: List[Tuple[str, float]],
                       rel_tol=0.001):

    for criteria, value in suffixes:
        exact_matches = []
        search_pattern = "{}_({})".format(criteria, FLOAT_REGEX)
        for candidate in candidates:
            match = re.search(search_pattern, candidate)
            if match:
                data_value = float(match.group(1))
                if value == 0.0 and data_value == 0.0:
                    exact_matches.append(candidate)
                elif abs(data_value - value) / abs(value) <= rel_tol:
                    exact_matches.append(candidate)
        candidates = exact_matches
    return candidates


def load_specific_data_file(file_name: str, pin_name: str, size: float = 1,
                            size_suffixes: List[Tuple[str, float]] = None,
                            interpolate_size_suffixes: bool = True) -> Union[float, None]:
    if not os.path.exists(file_name):
        return None
    with open(file_name, "r") as data_file:
        char_data = json.load(data_file)

    if pin_name in char_data:
        pin_data = char_data[pin_name]
    elif pin_name.lower() in char_data:
        pin_data = char_data[pin_name.lower()]
    else:
        return None

    if not pin_data:
        return None

    # if only one entry, return immediately
    if len(pin_data) == 1 and (not size_suffixes or interpolate_size_suffixes):
        return next(iter(pin_data.values()))

    if size_suffixes is None:
        size_suffixes = []

    closest_matches = filter_suffixes(size_suffixes, list(pin_data.keys()))
    if not closest_matches:
        return None

    # group by size
    search_pattern = "size_({})".format(FLOAT_REGEX)
    closest_matches = list(filter(lambda x: re.search(search_pattern, x), closest_matches))
    match_groups = groupby(closest_matches,
                           lambda x: float(re.search(search_pattern, x).group(1)))
    match_groups = {key: list(value) for key, value in match_groups}

    def mean_group(group_):
        return sum([pin_data[x] for x in group_]) / len(group_)

    if len(match_groups) == 1:
        candidates = next(iter(match_groups.values()))
        if not interpolate_size_suffixes:  # ensure exact match
            candidates = find_exact_matches(candidates, size_suffixes)
        if not candidates:
            return None

        return mean_group(next(iter(match_groups.values())))
    elif size in match_groups:
        return mean_group(match_groups[size])
    elif size >= max(match_groups.keys()):
        return mean_group(match_groups[max(match_groups.keys())])
    elif size <= min(match_groups.keys()):
        return mean_group(match_groups[min(match_groups.keys())])
    else:
        # find two closest and interpolate
        lower_size = min(filter(lambda x: x < size, match_groups.keys()),
                         key=lambda x: size - x)
        lower_value = mean_group(match_groups[lower_size])
        upper_size = min(filter(lambda x: x > size, match_groups.keys()),
                         key=lambda x: x - size)
        upper_value = mean_group(match_groups[upper_size])
        t = (size - lower_size) / (upper_size - lower_size)
        return (1 - t) * lower_value + t * upper_value


def load_data(cell_name: str, pin_name: str, size: float = 1,
              file_suffixes: List[Tuple[str, float]] = None,
              size_suffixes: List[Tuple[str, float]] = None,
              interpolate_size_suffixes: bool = True) -> Union[float, None]:
    """
    Save data from characterization to json
    :param cell_name: name of characterized cell
    :param pin_name: characterized pin
    :param size: characterized cell size. Leave as one for cells with just one size
    :param file_suffixes: e.g. height or beta where relevant.
                         height is relevant for example inverters.
                         ("height", 1) adds _height_1 to file name
    :param size_suffixes: e.g. number of fingers or word_size.
                          Adds suffix to the size key similar to file_suffixes
    :param interpolate_size_suffixes: if false, exact match for size suffixes is used, otherwise None
    :return: closest value from characterization or None if no data is saved
    """
    if not file_suffixes:
        file_suffixes = []

    sample_file = get_data_file(cell_name, [])
    candidate_files = []
    for file_name in os.listdir(os.path.dirname(sample_file)):
        if file_name.startswith(cell_name) and file_name.endswith(".json"):
            candidate_files.append(file_name)

    def clean_name(name):
        name = name.replace(cell_name, "")  # when there are no suffixes
        return name.replace(".json", "")

    trimmed_names = [clean_name(x) for x in candidate_files]
    matched_files = filter_suffixes(file_suffixes, trimmed_names)

    # return the average value for all the matches
    values = []
    for matched_file in matched_files:
        full_file_name = os.path.join(os.path.dirname(sample_file),
                                      cell_name + matched_file + ".json")
        data_from_file = load_specific_data_file(full_file_name, pin_name, size,
                                                 size_suffixes, interpolate_size_suffixes)
        if data_from_file is not None:
            values.append(data_from_file)
    if values:
        return sum(values) / len(values)
    return None
