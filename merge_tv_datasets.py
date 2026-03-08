import pandas as pd
from thefuzz import fuzz


TARGET_CHARACTERS = ["Sheldon", "Leonard", "Michael", "Dwight"]
THRESHOLD = 74  # 0.74 expressed on thefuzz's 0-100 scale


def clean_character(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.replace(r"\s*\(.*?\)", "", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


def fuzzy_standardize(series: pd.Series, targets: list[str], threshold: int) -> pd.Series:
    def map_name(name: str) -> str:
        if not name or name.lower() == "nan":
            return name

        for target in targets:
            if fuzz.ratio(name, target) >= threshold:
                return target
        return name

    return series.apply(map_name)


def prepare_tbbt(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    df["scene"] = (df["character"] == "Scene").astype(int)
    df["scene"] = df.groupby(["season", "episode"])["scene"].cumsum()

    df = df[["season", "episode", "scene", "character", "dialogue"]].copy()
    df["show"] = "The Big Bang Theory"

    return df[["show", "season", "episode", "scene", "character", "dialogue"]]


def prepare_office(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    df = df.rename(columns={"speaker": "character", "line": "dialogue"})
    df = df[["season", "episode", "scene", "character", "dialogue"]].copy()
    df["show"] = "The Office"

    return df[["show", "season", "episode", "scene", "character", "dialogue"]]


def main() -> None:
    tbbt = prepare_tbbt("TheBigBangTheory_scraped.csv")
    office = prepare_office("TheOffice.csv")

    merged = pd.concat([tbbt, office], ignore_index=True)

    merged["character"] = clean_character(merged["character"])
    merged["character"] = fuzzy_standardize(merged["character"], TARGET_CHARACTERS, THRESHOLD)

    merged.to_csv("merged_tv_dialogues.csv", index=False)

    print("Wrote merged_tv_dialogues.csv")
    print("Rows:", len(merged))
    print("Columns:", merged.columns.tolist())


if __name__ == "__main__":
    main()
