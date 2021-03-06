import os

import geopandas as gpd
import numpy as np
import pandas as pd
import dash_html_components as html

VOC = sorted( ["B.1.1.7", "B.1.351", "B.1.617.2", "P.1", "P.1.1", "P.1.2"] )
VOI = sorted( ["B.1.427", "B.1.429", "B.1.525", "B.1.526", "B.1.526.1", "B.1.526.2", "B.1.617", "B.1.617.1", "B.1.617.3", "P.2", "B.1.1.318", "P.3", "C.36.3", "C.37"] )

def load_sequences( window=None ):
    sequences = pd.read_csv( "resources/sequences.csv" )

    # Convert to dates correctly.
    sequences["collection_date"] = pd.to_datetime( sequences["collection_date"] ).dt.tz_localize( None )
    sequences["collection_date"] = sequences["collection_date"].dt.normalize()
    sequences["epiweek"] = pd.to_datetime( sequences["epiweek"] ).dt.tz_localize( None )
    sequences["epiweek"] = sequences["epiweek"].dt.normalize()

    sequences["zipcode"] = sequences["zipcode"].apply( lambda x: f"{x:.0f}" )

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

def get_seqs_per_case( time_series, seq_md, zip_f=None ):
    """ Combines timeseries of cases and sequences.
    Parameters
    ----------
    time_series
    seq_md
    zip_f

    Returns
    -------

    """
    if zip_f:
        if type( zip_f ) != list:
            zip_f = [zip_f]
        time_series = time_series.loc[time_series["ziptext"].isin(zip_f)]
    cases = time_series.pivot_table( index="updatedate", values="case_count", aggfunc="sum" )
    cases["case_count"] = np.maximum.accumulate( cases["case_count"] )
    cases = cases.reset_index()

    cases.columns = ["date", "cases"]

    cases = cases.merge( get_seqs( seq_md, zip_f=zip_f ), on="date", how="outer", sort=True )

    cases["new_sequences"] = cases["new_sequences"].fillna( 0.0 )
    cases["sequences"] = cases["new_sequences"].cumsum()
    cases = cases.loc[~cases["cases"].isna()]
    cases["new_cases"] = cases["cases"].diff()
    cases["new_cases"] = cases["new_cases"].fillna( 0.0 )
    cases.loc[cases["new_cases"] < 0,"new_cases"] = 0

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
    zip_area.loc[zip_area["fraction"].isna(),"fraction"] = 0
    zip_area = zip_area.set_index( "ZIP" )

    # Removing a number of columns to save memory.
    zip_area = zip_area[["geometry", "case_count","sequences", "fraction"]]

    return zip_area

def format_zip_summary( cases, seqs ):
    """ Merges cummulate cases and sequences for each ZIP code.
    Parameters
    ----------
    cases : pandas.DataFrame
        output of format_cases_total( load_cases() ) containing the cummulative cases for each zip code.
    seqs : pandas.DataFrame
        output of download_search() or load_sequences() containing a lkist of sequences with ZIP code information.
    Returns
    -------
    pandas.DataFrame :
        DataFrame linking ZIP code to case counts, sequences, and fraction of cases sequenced. Use format_shapefile() if
        want GeoDataFrames.
    """
    cumulative_seqs = get_seqs( seqs, groupby="zipcode" )

    cumulative_seqs = cumulative_seqs.merge( cases[["ziptext", "case_count"]], left_on="zip", right_on="ziptext", how="right" )
    cumulative_seqs["sequences"] = cumulative_seqs["sequences"].fillna( 0.0 )
    cumulative_seqs["fraction"] = cumulative_seqs["sequences"] / cumulative_seqs["case_count"]
    cumulative_seqs.loc[cumulative_seqs["fraction"].isna(),"fraction"] = 0
    cumulative_seqs = cumulative_seqs.drop( columns=["zip"] )

    return cumulative_seqs



def get_lineage_values( seqs ):
    values = seqs["lineage"].dropna()
    values = values.sort_values().unique()


    return_dict = [{"label" : "All variants of concern", "value" : "all-voc" },
                   {"label" : " - Variants of concern" , "value" : "None", "disabled" : True}]
    for i in VOC:
        if i in values:
            return_dict.append( { "label" : i, "value" : i } )

    return_dict.append( {"label" : " - Variants of interest" , "value" : "None", "disabled" : True} )
    for i in VOI:
        if i in values:
            return_dict.append( { "label" : i, "value" : i } )

    return_dict.append( {"label" : " - PANGO lineages" , "value" : "None", "disabled" : True} )
    for i in values:
        if ( i not in VOC ) & ( i not in VOI ):
            return_dict.append( { "label" : i, "value" : i } )

    return return_dict

def get_summary_table( seqs ):
    sg = {"textAlign" : "center" }
    sd2 = {"marginLeft" : "50px" }
    table = [html.Tr( [html.Th( "Type", style={"marginLeft" : "20px" } ), html.Th( "Total", style=sg ), html.Th( "Last Month", style=sg )] ),
             html.Tr( [html.Td( html.B( "Sequences", style={"marginLeft" : "10px" } ) ), html.Td( len( seqs ), style=sg ), html.Td( len( seqs.loc[seqs['days_past'] < 30] ), style=sg )] ),
             html.Tr(html.Td( "", colSpan=3 ) ),
             html.Tr( html.Td( html.B( "Variants of concern", style={"marginLeft" : "10px" } ), colSpan=3))]
    for i in VOC:
        if i in seqs["lineage"].unique():
            table.append( html.Tr( [html.Td( html.I( i, style={"marginLeft" : "20px" } ) ), html.Td( len( seqs.loc[seqs['lineage']==i] ), style=sg ), html.Td( len( seqs.loc[(seqs['lineage']==i)&(seqs['days_past']<30)] ), style=sg )] ) )

    return table

def get_provider_sequencer_values( seqs, value ):
    labels = [{"label" : f"{i} ({j})", "value": i }for i, j in seqs[value].sort_values().value_counts().iteritems()]
    labels = sorted( labels, key=lambda x: x["label"] )
    return labels