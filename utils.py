import difflib
from typing import List

import polars as pl
import polars_ds as pds


def longest_common_subsequence(str1, str2):
    sequence_matcher = difflib.SequenceMatcher(None, str1, str2)
    match = sequence_matcher.find_longest_match(0, len(str1), 0, len(str2))
    return {"lcs": str1[match.a : match.a + match.size], "start_index": match.a}


# Define the function to compute the similarity ratio
def similarity_ratio(lcs, str1, str2):
    return len(lcs) / max(min(len(str1), len(str2)), 1)


def get_hash_map(
    df, terms: List[str], col_name="description", col_name_to_match="for_maarten"
):
    assert col_name in df.columns, f"The DataFrame should have a {col_name} column"

    def normalize_col(col_name: str) -> pl.Expr:
        return (
            pds.normalize_whitespace(
                pds.remove_diacritics(
                    pl.col(col_name)
                    .str.to_lowercase()
                    .str.strip_chars()
                    .str.replace_all(r"\s+", " ")
                    .str.split(" ")
                    .list.set_difference(["boni", "bio", "everyday"])
                    .list.set_difference(pds.extract_numbers(col_name))
                    .list.join(" ")
                )
            )
        ).alias(f"{col_name}_normalized")

    cross_joined = df.with_columns(pl.lit(terms).alias(col_name_to_match)).explode(
        col_name_to_match
    )

    output = (
        cross_joined.with_columns(
            normalize_col(col_name), normalize_col(col_name_to_match)
        )
        .with_columns(
            [
                pl.struct(f"{col_name}_normalized", f"{col_name_to_match}_normalized")
                .map_elements(
                    lambda x: longest_common_subsequence(
                        x[f"{col_name}_normalized"],
                        x[f"{col_name_to_match}_normalized"],
                    ),
                    return_dtype=pl.Struct({"lcs": pl.Utf8, "start_index": pl.Int64}),
                )
                .alias("lcs_struct")
            ]
        )
        .unnest("lcs_struct")
        .with_columns(pl.col("lcs").str.len_chars().alias("lcs_len"))
        .with_columns(
            pl.struct("lcs", col_name, col_name_to_match)
            .map_elements(
                lambda row: similarity_ratio(
                    row["lcs"], row[col_name], row[col_name_to_match]
                ),
                return_dtype=pl.Float64,
            )
            .alias("similarity_ratio"),
            pl.col("lcs").str.len_chars().alias("lcs_length"),
        )
        .with_columns(
            pl.col("similarity_ratio")
            .max()
            .over(col_name)
            .alias("max_similarity_ratio")
        )
        .filter(pl.col("similarity_ratio") == pl.col("max_similarity_ratio"))
        .unique("description")
    )

    return output.filter(pl.col("similarity_ratio") >= 0.8)
