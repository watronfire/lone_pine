import datetime

#import geojson_rewind
import geopandas as gpd
import pandas as pd
import json
from epiweeks import Week

# Download metadata from SEARCH repository
# https://raw.githubusercontent.com/andersen-lab/HCoV-19-Genomics/master/metadata.csv
def download_search():
    """ Downloads the metadata from the SEARCH github repository. Removes entries with very wrong dates.
    Returns
    -------
    pandas.DataFrame:
        Data frame containing the metadata for all sequences generated by SEARCH
    """

    search_md = "https://raw.githubusercontent.com/andersen-lab/HCoV-19-Genomics/master/metadata.csv"
    md = pd.read_csv( search_md )
    drop_cols = [i for i in md.columns if i not in ["ID", "collection_date", "location", "authors", "originating_lab", "zipcode"]]
    md = md.drop( columns=drop_cols )
    md = md.loc[md["location"]=="USA/California/San Diego"]
    md = md.loc[md["collection_date"]!='Unknown']
    md = md.loc[~md["collection_date"].str.startswith( "19" )]
    md = md.loc[~md["collection_date"].str.contains( "/" )]
    md = md.loc[md["collection_date"] != "NaT"]

    md["epiweek"] = md["collection_date"].apply( lambda x: Week.fromdate( datetime.datetime.strptime( x, "%Y-%m-%d" ).date() ).startdate() )
    md["collection_date"] = pd.to_datetime( md["collection_date"], format="%Y-%m-%d" ).dt.normalize()
    md["days_past"] = ( md["collection_date"].max() - md["collection_date"] ).dt.days

    md["originating_lab"] = md["originating_lab"].replace( {'UC San Diego Center for Advanced Laboratory Medicine' :  "UCSD CALM Lab",
                                                            "UCSD EXCITE" : "UCSD EXCITE Lab",
                                                            "EXCITE Lab" : "UCSD EXCITE Lab",
                                                            "Andersen lab at Scripps Research" : "SD County Public Health Laboratory",
                                                            "San Diego County Public Health Laboratory" : "SD County Public Health Laboratory",
                                                            "Sharp HealthCare Laboratory" : "Sharp Health",
                                                            "Scripps Medical Laboratory" : "Scripps Health"} )

    # Add pangolin lineage information
    pango_loc = "https://raw.githubusercontent.com/andersen-lab/HCoV-19-Genomics/master/lineage_report.csv"
    pango = pd.read_csv( pango_loc, usecols=["taxon", "lineage"] )

    md = md.merge( pango, left_on="ID", right_on="taxon", how="left" )

    return md


# Grab covid statistics from data repository
# https://gis-public.sandiegocounty.gov/arcgis/rest/services/Hosted/COVID_19_Statistics__by_ZIP_Code/FeatureServer/0/query?outFields=*&where=1%3D1

# TODO: Needs to refactor for the new geojson format. ziptext -> Zip Text, case_count -> Case Count, updatedate -> Update Date
def download_cases():
    """ Downloads the cases per San Diego ZIP code. Appends population.
    Returns
    -------
    pandas.DataFrame
        DataFrame detailing the cummulative cases in each ZIP code.
    """
    def _append_population( dataframe ):
        pop_loc = "resources/zip_pop.csv"
        pop = pd.read_csv( pop_loc )
        pop = pop.set_index( "Zip" )
        pop["Total Population"] = pd.to_numeric( pop["Total Population"].str.replace( ",", "" ) )
        pop = pop["Total Population"].to_dict()
        dataframe["population"] = dataframe["ziptext"].map( pop )
        return dataframe

    cases_loc = "https://opendata.arcgis.com/datasets/854d7e48e3dc451aa93b9daf82789089_0.geojson"
    return_df = gpd.read_file( cases_loc )
    return_df = return_df[["ziptext","case_count", "updatedate"]]
    return_df["updatedate"] = pd.to_datetime( return_df["updatedate"] ).dt.tz_localize( None )
    return_df["updatedate"] = return_df["updatedate"].dt.normalize()
    return_df["ziptext"] = pd.to_numeric( return_df["ziptext"] )
    return_df = return_df.groupby( ["updatedate", "ziptext"] ).last().reset_index()
    return_df = return_df.sort_values( "updatedate" )

    # Calculate cases per day because thats way more useable than cummulative counts.
    return_df = _append_population( return_df )
    return_df["case_count"] = return_df["case_count"].fillna( 0 )
    return_df["new_cases"] = return_df.groupby( "ziptext" )["case_count"].diff()
    return_df["new_cases"] = return_df["new_cases"].fillna( return_df["case_count"] )
    return_df.loc[return_df["new_cases"]<0, "new_cases"] = 0

    return_df["days_past"] = ( datetime.datetime.today() - return_df["updatedate"] ).dt.days

    return_df["case_count"] = return_df.groupby( "ziptext" )["new_cases"].cumsum()

    return return_df

def download_shapefile():
    shapefile_loc = "https://opendata.arcgis.com/datasets/41c3a7bd375547069a78fce90153cbc0_5.geojson"
    zip_area = gpd.read_file( shapefile_loc )
    zip_area = zip_area[["ZIP", "geometry"]].dissolve( by="ZIP" )
    zip_area = zip_area.reset_index()

    # GeoJSON from San Diego has improper winding so I have to fix it.
    zip_area = zip_area.set_geometry(
        gpd.GeoDataFrame.from_features(
            json.loads(
                geojson_rewind.rewind(
                    zip_area.to_json(),
                    rfc7946=False
                )
            )["features"]
        ).geometry
    )

    return zip_area

if __name__ == "__main__":
    seqs_md = download_search()
    seqs_md.to_csv( "resources/sequences.csv", index=False )

    cases = download_cases()
    cases.to_csv( "resources/cases.csv", index=False )

    #sd_zips = download_shapefile()
    #sd_zips.to_file("resources/zips.geojson", driver='GeoJSON' )
