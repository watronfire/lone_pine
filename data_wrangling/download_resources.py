import geojson_rewind
import geopandas as gpd
import pandas as pd
import numpy as np
import json
import dashboard.plot as dashplot

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
    drop_cols = [i for i in md.columns if i not in ["ID", "collection_date", "location", "authors", "originating_lab"]]
    md = md.drop( columns=drop_cols )
    md = md.loc[md["collection_date"]!='Unknown']
    md = md.loc[~md["collection_date"].str.startswith( "19" )]
    md = md.loc[~md["collection_date"].str.contains( "/" )]
    md["collection_date"] = pd.to_datetime( md["collection_date"], format="%Y-%m-%d" ).dt.normalize()
    return md

def download_shapefile( cases, seqs, save=False, local=False ):
    """ Downloads and formats the San Diego ZIP GeoJSON formatted as a dictionary.
    Returns
    -------
    dict
    """
    if local:
        zip_area = gpd.read_file( "resources/zips.geojson")
    else:
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

    if save:
        zip_area.to_file("resources/zips.geojson", driver='GeoJSON' )



    # Add case data so it is there...
    zip_area = zip_area.merge( cases, left_on="ZIP", right_on="ziptext" )
    zip_area = zip_area.merge( get_seqs( seqs, groupby="zip" ), left_on="ZIP", right_on="zip" )
    zip_area["fraction"] = zip_area["sequences"] / zip_area["case_count"]
    zip_area = zip_area.set_index( "ZIP" )

    # Removing a number of columns to save memory.
    zip_area = zip_area[["geometry", "case_count","sequences", "fraction"]]

    return zip_area

# Grab covid statistics from data repository
# https://gis-public.sandiegocounty.gov/arcgis/rest/services/Hosted/COVID_19_Statistics__by_ZIP_Code/FeatureServer/0/query?outFields=*&where=1%3D1
def download_cases():
    """ Downloads the cases per San Diego ZIP code. Appends population and ZIP code shapefile.
    Returns
    -------
    pandas.DataFrame
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
    # Open COVID-19 dataset and perform basic formating, dropping columns, converting to correct type. Note: the
    # downloaded file is a geojson but we drop the geometry parameter.
    return_df = gpd.read_file( cases_loc )
    return_df = return_df.drop( columns=['zipcode_zip', 'created_user', 'created_date',
                                         'last_edited_user', 'last_edited_date', 'globalid', "geometry"] )
    return_df["updatedate"] = pd.to_datetime( return_df["updatedate"] ).dt.tz_localize( None )
    return_df["updatedate"] =  return_df["updatedate"].dt.normalize()
    return_df["ziptext"] = pd.to_numeric( return_df["ziptext"] )
    return_df = return_df.groupby( ["updatedate", "ziptext"] ).first().reset_index()

    # Add population for each zip and calculate values per 100000 inhabitants.
    return_df = _append_population( return_df )
    return_df["rate_100k"] = ( return_df["case_count"] / return_df["population"] ) * 100000
    return_df["test_100k"] = ( return_df["test_total"] / return_df["population"] ) * 100000
    return_df["tests_pct_positive"] = return_df['test_positive'] / return_df["test_total"]
    return_df.loc[return_df["population"] < 1000, "rate_100k"] = np.nan
    return_df.loc[return_df["population"] < 1000, "test_100k"] = np.nan

    ts_df = return_df.melt( id_vars=["updatedate", "ziptext"], value_vars=['case_count', 'rate_100k'] )

    # For one dataset only keep the most recent data.
    return_df = return_df.sort_values( "updatedate", ascending=False ).groupby( "ziptext" ).first()
    return_df = return_df.reset_index()

    #return_df = _append_shapefile( return_df )

    return return_df, ts_df

def get_seqs( seq_md, groupby="collection_date", zip_f=None ):
    if zip_f:
        seqs = seq_md.loc[seq_md["zip"].isin( zip_f )]
    else:
        seqs = seq_md

    seqs = seqs.groupby( groupby )["ID"].agg( "count" ).reset_index()
    if groupby == "collection_date":
        seqs.columns = ["date", "new_sequences"]
    elif groupby == "zip":
        seqs.columns = ["zip", "sequences"]

    return seqs

def get_seqs_per_case( time_series, seq_md, zip_f=None, normalized=False ):
    field = "case_100k" if normalized else "case_count"

    query = time_series["variable"]==field
    if zip_f:
        if type( zip_f ) != list:
            zip_f = [zip_f]
        query = query & ( time_series["ziptext"].isin( zip_f ) )
    cases = time_series.loc[query].pivot_table( index="updatedate", values="value", aggfunc="sum" )
    cases = cases.fillna( 0.0 )
    cases = cases.reset_index()

    cases.columns = ["date", "cases"]

    #cases = cases.merge( get_seqs( seq_md ), on="date", how="outer", sort=True )

    try:
        cases = cases.merge( get_seqs( seq_md, zip_f=zip_f ), on="date", how="outer", sort=True )
    except ValueError:
        print( cases.head() )
        print( get_seqs( seq_md ).head() )
        print( cases.dtypes )
        print( get_seqs( seq_md ).dtypes )
        exit( 1 )


    cases["new_sequences"] = cases["new_sequences"].fillna( 0.0 )
    cases["sequences"] = cases["new_sequences"].cumsum()
    #cases.to_csv( "resources/temp.csv" )
    cases = cases.loc[~cases["cases"].isna()]
    cases["new_cases"] = cases["cases"].diff()
    cases["new_cases"] = cases["new_cases"].fillna( 0.0 )
    cases.loc[cases["new_cases"] < 0,"new_cases"] = 0
    cases["fraction"] = cases["sequences"] / cases["cases"]

    return cases

#def date_lim( date ):

if __name__ == "__main__":
    md = pd.read_csv( "resources/md.csv" )
    md = md.loc[md["collection_date"]!='Unknown']
    md = md.loc[~md["collection_date"].str.startswith( "19" )]
    md = md.loc[~md["collection_date"].str.contains( "/" )]
    md["collection_date"] = pd.to_datetime( md["collection_date"], format="%Y-%m-%d" ).dt.normalize()
    df, ts = download_cases()
    zips = download_shapefile( df, md, local=True )
    plot_df = get_seqs_per_case( ts, md )

    fig = dashplot.plot_choropleth( zips )
    fig.show()

    #fig = dashplot.plot_daily_cases_seqs( plot_df )
    #fig.show()