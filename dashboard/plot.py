import plotly.graph_objects as go
import plotly.express as px
import numpy as np
import pandas as pd
from epiweeks import Week

VOC = sorted( ["B.1.1.7", "B.1.351", "B.1.617.2", "P.1", "P.1.1", "P.1.2"] )
VOI = sorted( ["B.1.427", "B.1.429", "B.1.525", "B.1.526", "B.1.526.1", "B.1.526.2", "B.1.617", "B.1.617.1", "B.1.617.3",
     "P.2", "B.1.1.318", "P.3", "C.36.3", "C.37"] )


def _add_date_formating( fig ):
    for i in range( 2, 19, 2 ):
        year1 = 2020
        year2 = 2020
        month1 = i
        month2 = i + 1
        if i > 12:
            year1 += 1
            year2 += 1
            month1 -= 12
            month2 -= 12
        elif i == 12:
            year2 += 1
            month2 -= 12
        fig.add_vrect( x0=f"{year1}-{month1}-01", x1=f"{year2}-{month2}-01", fillcolor="#EFEFEF", opacity=1, layer="below" )

    fig.update_xaxes( dtick="M1", tickformat="%b\n%Y", mirror=True )
    fig.update_yaxes( mirror=True )
    fig.update_layout( template="simple_white",
                       hovermode="x unified",
                       plot_bgcolor="#ffffff",
                       paper_bgcolor="#ffffff",
                       margin={"r":0,"t":0,"l":0,"b":0},
                       legend=dict( yanchor="top",
                                    y=0.99,
                                    xanchor="left",
                                    x=0.01,
                                    bgcolor="rgba(0,0,0,0)" ) )

def get_date_limits( series ):
    # Max
    year = series.max().year
    month = series.max().month + 1
    day = 1
    max_lim = pd.to_datetime( f"{year}-{month}-{day}" )

    # min
    year = series.min().year
    month = series.min().month
    day = 1
    min_lim = pd.to_datetime( f"{year}-{month}-{day}" )
    return [min_lim, max_lim]

def plot_daily_cases_seqs( df ):
    fig = go.Figure()
    fig.add_trace( go.Scattergl( x=df["date"], y=df["new_cases"],
                                 mode='markers',
                                 name='Daily Cases',
                                 marker={ "color" : "#767676" } ) )
    fig.add_trace(go.Scattergl(x=df["date"], y=df["new_sequences"],
                               mode='markers',
                               name='Daily Sequences',
                               marker={ "color" : "#DFB377"} ) )

    _add_date_formating( fig )
    min_lim = np.floor( np.log10( 0.75 ) )
    max_lim = np.ceil( np.log10( df["new_cases"].max() ) )
    fig.update_yaxes( type="log", dtick=1, title="<b>Number of cases</b>", range=[min_lim, max_lim] )
    fig.update_xaxes( range=get_date_limits( df["date"] ) )

    return fig

def plot_cummulative_cases_seqs( df ):
    fig = go.Figure()
    fig.add_trace( go.Scattergl( x=df["date"], y=df["cases"],
                               mode='lines',
                               name='Reported',
                               line={ "color" : '#767676', "width" : 4 } ) )
    fig.add_trace(go.Scattergl(x=df["date"], y=df["sequences"],
                             mode='lines',
                             name='Sequenced',
                             line={ "color" : "#DFB377", "width" : 4 } ) )

    _add_date_formating( fig )
    min_lim = np.floor( np.log10( df.loc[df["sequences"] > 0,"sequences"].min() ) )
    max_lim = np.ceil( np.log10( df["cases"].max() ) )
    fig.update_yaxes( type="log", dtick=1, title="<b>Cummulative cases</b>", range=[min_lim, max_lim] )
    fig.update_xaxes( range=get_date_limits( df["date"] ) )

    return fig

def plot_cummulative_sampling_fraction( df ):
    df["epiweek"] = df["date"].apply( lambda x: Week.fromdate(x).startdate() )
    plot_df = df.groupby( "epiweek" ).agg( new_cases = ("new_cases", "sum"), new_sequences = ("new_sequences", "sum" ) )
    plot_df = plot_df.loc[plot_df["new_sequences"]>0]
    plot_df["fraction"] = plot_df["new_sequences"] / plot_df["new_cases"]
    plot_df = plot_df.reset_index()

    fig = go.Figure()
    fig.add_trace( go.Scattergl( x=plot_df["epiweek"], y=plot_df["fraction"],
                                 mode='lines',
                                 name='Fraction',
                                 line={ "color" : '#767676', "width" : 4 } ) )

    _add_date_formating( fig )

    fig.update_layout( yaxis_tickformat='.1%' )

    cleaned_array = np.log10( plot_df.loc[plot_df["fraction"] > 0, "fraction"] )
    cleaned_array = cleaned_array[~np.isinf( cleaned_array )]

    min_lim = np.floor( cleaned_array.min() )
    max_lim = np.ceil( cleaned_array.max() )

    fig.update_yaxes( type="log", title="<b>Cases sequenced (%)</b>" )
    fig.update_xaxes( range=get_date_limits( plot_df["epiweek"] ) )

    return fig

def add_missing_to_color_scale( scale, color="white" ):
    return_list = [[0, color],
                   [0.01, color]]
    len_scale = len( scale ) - 1
    for i, col in enumerate( scale ):
        if i == 0:
            return_list.append( [0.01, col] )
        else:
            return_list.append( [( 1 / len_scale ) * i, col] )
    return return_list

def plot_choropleth( sf, colorby="fraction" ):
    # TODO: This plot would be easier to read in a log scale.
    #  Requires modifying sf, the hoverdata, and then the colorscale.
    #  Ref: https://community.plotly.com/t/how-to-make-a-logarithmic-color-scale-in-my-choropleth-map/35010/3

    fig = px.choropleth( sf, geojson=sf.geometry,
                         locations=sf.index, color=colorby,
                         labels={"fraction": "Sequences per case",
                                 "case_count" : "Cases",
                                 "sequences" : "Sequences" },
                         hover_data=[ "case_count", "sequences", "fraction" ],
                         projection="mercator", color_continuous_scale=px.colors.sequential.Bluyl,
                         basemap_visible=False, fitbounds="geojson", scope=None )
    fig.update_geos( bgcolor="#ffffff" )
    fig.update_layout( autosize=True,
                       plot_bgcolor="#ffffff",
                       paper_bgcolor="#ffffff",
                       margin={"r":0,"t":0,"l":0,"b":0} )
    return fig

def plot_lineages_time( df, lineage=None, scaleby="fraction" ):

    plot_df = df.pivot_table( index="epiweek", columns="lineage", values="ID", aggfunc="count" )
    plot_df = plot_df.fillna( 0 )

    yaxis_label = "Sequences"

    if scaleby == "fraction":
        plot_df = plot_df.apply( lambda x: x / x.sum(), axis=1 )
        yaxis_label += " (%)"

    max_lim = np.round( plot_df.sum( axis=1 ).max() * 1.05 )

    fig = go.Figure()

    if lineage is not None:
        focus_df = plot_df[lineage]
        plot_df = plot_df.drop( columns=lineage )
        plot_df = plot_df.sum( axis=1 )
        plot_df = pd.concat( [focus_df, plot_df], axis=1 )
        plot_df.columns = [lineage, "all"]
        fig.add_trace( go.Bar( x=plot_df.index, y=plot_df[lineage], name=lineage, marker_color="#DFB377" ) )
    else:
        plot_df = plot_df.sum(axis=1).reset_index()
        plot_df.columns = ["epiweek", "all"]
        plot_df = plot_df.set_index( "epiweek" )

    if scaleby == "fraction":
        fig.update_layout( yaxis_tickformat='.1%' )

    fig.add_trace( go.Bar( x=plot_df.index, y=plot_df["all"], name="All", marker_color='#767676' ) )
    fig.update_layout(barmode='stack')
    fig.update_yaxes( showgrid=False, title=f"<b>{yaxis_label}</b>", range=[0,max_lim] )
    fig.update_xaxes( range=get_date_limits( df["collection_date"] ) )
    _add_date_formating( fig )

    return fig

def plot_lineages( df ):

    plot_df = df["lineage"].value_counts().reset_index()

    colors = list()
    for i in plot_df["index"]:
        if i in VOI:
            colors.append( "#4977CE" )
        elif i in VOC:
            colors.append( "#AC6D41" )
        else:
            colors.append( "#767676" )

    fig = go.Figure()
    fig.add_trace( go.Bar( x=plot_df["index"], y=plot_df["lineage"], marker_color=colors ) )
    fig.update_yaxes( showgrid=True, title="<b>Number of sequences</b>" )
    fig.update_xaxes( title="<b>PANGO lineage</b>" )

    if len( plot_df ) > 50:
        fig.update_xaxes( range=[-0.5, 50.5] )
    else:
        fig.update_xaxes( range=[-0.5, len( plot_df ) - 0.5] )

    fig.update_layout( template="simple_white",
                       plot_bgcolor="#ffffff",
                       paper_bgcolor="#ffffff",
                       margin={"r":0,"t":0,"l":0,"b":0},
                       legend=dict( yanchor="top",
                                    y=0.99,
                                    xanchor="left",
                                    x=0.01,
                                    bgcolor="rgba(0,0,0,0)" ) )
    return fig

def plot_voc( df, scaleby="fractions" ):
    included_voc = [i for i in VOC if i in df["lineage"].unique()]

    plot_df = df.pivot_table( index="epiweek", columns="lineage", values="state", aggfunc="count", fill_value=0 )
    voc_df = plot_df[included_voc]
    voc_df = voc_df.reindex( columns=voc_df.sum().sort_values( ascending=False ).index )
    other_df = plot_df[plot_df.columns.difference( included_voc )]
    other_df = other_df.sum( axis=1 )
    other_df.name = "Other"
    plot_df = voc_df.merge( other_df, left_index=True, right_index=True )

    yaxis_label = "Sequences"
    if scaleby == "fraction":
        plot_df = plot_df.apply( lambda x: x / x.sum(), axis=1 )
        yaxis_label += " (%)"

    max_lim = np.round( plot_df.sum( axis=1 ).max() * 1.05 )

    fig = go.Figure()
    for i, j in enumerate( plot_df ):
        if j == "Other":
            color = "#767676"
        else:
            color = px.colors.colorbrewer.Set1[i]

        fig.add_trace( go.Bar( x=plot_df.index, y=plot_df[j], name=j, marker_color=color ) )

    if scaleby == "fraction":
        fig.update_layout( yaxis_tickformat='.1%' )

    fig.update_layout( barmode='stack' )
    fig.update_yaxes( showgrid=False, title=f"<b>Sequences (%)</b>", range=[0, max_lim] )
    fig.update_xaxes( range=get_date_limits( plot_df.index ) )
    fig.update_layout( legend=dict( bgcolor="rgba(256,256,256,256)" ) )
    _add_date_formating( fig )

    return fig


def plot_zips( df, colorby="sequences" ):
    fig = go.Figure()
    fig.add_trace( go.Bar( x=df["ziptext"], y=df[colorby], marker_color="#767676" ) )

    if colorby == "fraction":
        title="Cases sequenced (%)"
        fig.update_layout( yaxis_tickformat='.1%' )
    else:
        title="Number of sequences"

    max_lim = df[colorby].max() * 1.05
    if colorby == 'sequences':
        max_lim = np.round( max_lim )
    fig.update_yaxes( showgrid=True, title=f"<b>{title}</b>", range=[0,max_lim] )
    fig.update_xaxes( title="<b>ZIP code</b>", type="category", categoryorder="total descending" )
    if (df['sequences']>0).sum() > 65:
        fig.update_xaxes( range=[-0.5, 65.5] )
    else:
        fig.update_xaxes( range=[-0.5, (df['sequences']>0).sum() - 0.5] )
    fig.update_layout( template="simple_white",
                       plot_bgcolor="#ffffff",
                       paper_bgcolor="#ffffff",
                       margin={"r":0,"t":0,"l":0,"b":0},
                       legend=dict( yanchor="top",
                                    y=0.99,
                                    xanchor="left",
                                    x=0.01,
                                    bgcolor="rgba(0,0,0,0)" ) )
    return fig