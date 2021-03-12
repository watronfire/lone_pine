import geopandas as gpd
import pandas as pd

def load_sequences( window=None ):
    sequences = pd.read_csv( "resources/sequences.csv" )

    # Convert to dates correctly.
    sequences["collection_date"] = pd.to_datetime( sequences["collection_date"] ).dt.tz_localize( None )
    sequences["collection_date"] = sequences["collection_date"].dt.normalize()

    if window is not None:
        sequences = sequences.loc[sequences["days_past"] <= window].copy()

    return sequences


def load_cases( window = None ):
    cases = pd.read_csv( "resources/cases.csv" )

    # Convert to dates correctly.
    cases["updatedate"] = pd.to_datetime( cases["updatedate"] ).dt.tz_localize( None )
    cases["updatedate"] = cases["updatedate"].dt.normalize()

    if window is not None:
        cases = cases.loc[cases["days_past"] <= window].copy()
    return cases

def format_cases_timeseries( cases_df, window=None ):
    return cases_df.melt( id_vars=["updatedate", "ziptext"], value_vars=['case_count'] )


def format_cases_total( cases_df, window=None ):
    return_df = cases_df.sort_values( "updatedate", ascending=False ).groupby( "ziptext" ).first()
    return_df = return_df.reset_index()
    return return_df.drop( columns=["days_past"] )


def get_seqs_per_case( time_series, seq_md, zip_f=None, normalized=False ):
    """ Combines timeseries of cases and sequences.
    Parameters
    ----------
    time_series
    seq_md
    zip_f
    normalized

    Returns
    -------

    """
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
    cases = cases.loc[~cases["cases"].isna()]
    cases["new_cases"] = cases["cases"].diff()
    cases["new_cases"] = cases["new_cases"].fillna( 0.0 )
    cases.loc[cases["new_cases"] < 0,"new_cases"] = 0
    cases["fraction"] = cases["sequences"] / cases["cases"]

    return cases


def get_seqs( seq_md, groupby="collection_date", zip_f=None ):
    """ Pivots the output of download_search().
    Parameters
    ----------
    seq_md : pandas.DataFrame
        output of download_search(); list of sequences attached to ZIP code and collection date.
    groupby : str
        column of seq_md to count.
    zip_f : bool
        indicates whether to filter sequences to a single zipcode.

    Returns
    -------
    pandas.DatFrame
    """
    if zip_f:
        seqs = seq_md.loc[seq_md["zipcode"].isin( zip_f )]
    else:
        seqs = seq_md

    seqs = seqs.groupby( groupby )["ID"].agg( "count" ).reset_index()
    if groupby == "collection_date":
        seqs.columns = ["date", "new_sequences"]
    elif groupby == "zipcode":
        seqs.columns = ["zip", "sequences"]

    return seqs


def format_shapefile( cases, seqs ):
    """ Downloads and formats the San Diego ZIP GeoJSON formatted as a dictionary.
    Parameters
    ----------
    cases : pandas.DataFrame
        output of download_cases() containing the cummulative cases for each ZIP code.
    seqs : pandas.DataFrame
        output of download_search() containing a list of sequences with ZIP code information.
    Returns
    -------
    geopandas.GeoDataFrame:
        GeoDataFrame linking ZIP code areas to case counts, sequences, and fraction of cases sequenced.
    """
    zip_area = gpd.read_file( "resources/zips.geojson")

    # Add case data so it is there...
    zip_area = zip_area.merge( cases, left_on="ZIP", right_on="ziptext" )
    zip_area = zip_area.merge( get_seqs( seqs, groupby="zipcode" ), left_on="ZIP", right_on="zip", how="left" )
    zip_area["sequences"] = zip_area["sequences"].fillna( 0 )
    zip_area["fraction"] = zip_area["sequences"] / zip_area["case_count"]
    zip_area = zip_area.set_index( "ZIP" )

    # Removing a number of columns to save memory.
    zip_area = zip_area[["geometry", "case_count","sequences", "fraction"]]

    return zip_area

def get_lineage_values( seqs ):
    voc = ["B.1.1.7", "B.1.351", "P.1"]
    voi = ["B.1.427", "B.1.429", "B.1.526", "P.2"]

    values = seqs["lineage"].sort_values().unique()

    return_dict = [{"label" : " - Variants of concern" , "value" : "None", "disabled" : True}]
    for i in voc:
        if i in values:
            return_dict.append( { "label" : i, "value" : i } )

    return_dict.append( {"label" : " - Variants of interest" , "value" : "None", "disabled" : True} )
    for i in voi:
        if i in values:
            return_dict.append( { "label" : i, "value" : i } )

    return_dict.append( {"label" : " - PANGO lineages" , "value" : "None", "disabled" : True} )
    for i in values:
        if ( i not in voc ) & ( i not in voi ):
            return_dict.append( { "label" : i, "value" : i } )

    return return_dict