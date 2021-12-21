import datetime
import geopandas as gpd
import pandas as pd
import json
from epiweeks import Week
from scipy.optimize import curve_fit
from scipy.signal import savgol_filter
from numpy import exp, sqrt, diagonal, log

# Download metadata from SEARCH repository
# https://raw.githubusercontent.com/andersen-lab/HCoV-19-Genomics/master/metadata.csv
def load_excite_providers() :
    excite = pd.read_csv( "resources/0428_ccbb_full_metadata.csv", usecols=["search_id", "source" ] )
    excite = excite.set_index( "search_id" )
    return excite["source"].to_dict()

def load_file_as_list( loc ):
    with open( loc, "r" ) as open_file:
        return [line.strip() for line in open_file]

def download_search():
    """ Downloads the metadata from the SEARCH github repository. Removes entries with very wrong dates.
    Returns
    -------
    pandas.DataFrame:
        Data frame containing the metadata for all sequences generated by SEARCH
    """

    search_md = "https://raw.githubusercontent.com/andersen-lab/HCoV-19-Genomics/master/metadata.csv"
    md = pd.read_csv( search_md, usecols=["ID", "collection_date", "location", "authors", "originating_lab", "zipcode", "host"] )
    md["collection_date"] = md["collection_date"].astype( str )

    # Filter out incorrect samples or wastewater
    md = md.loc[md["ID"]!="SEARCH-104076"]
    #md = md.loc[~md["ID"].isin( load_file_as_list( "resources/ignore.txt") )]

    md = md.loc[(md["location"]=="North America/USA/California/San Diego")|(md["location"].str.startswith( "North America/Mexico/Baja California" ))]
    md = md.loc[md["collection_date"]!='Unknown']
    md = md.loc[~md["collection_date"].str.startswith( "19" )]
    md = md.loc[~md["collection_date"].str.contains( "/" )]
    md = md.loc[md["collection_date"] != "NaT"]
    md = md.loc[md["collection_date"] != "nan"]
    md = md.loc[md["host"]!="Environment"]

    # Generate an identifiable location column
    md["state"] = "Baja California"
    md.loc[md["location"]=="North America/USA/California/San Diego","state"] = "San Diego"

    #clean up zipcode
    md["zipcode"] = md["zipcode"].astype( "str" )
    md["zipcode"] = md["zipcode"].apply( lambda x: x.split( "-" )[0] )

    md["epiweek"] = md["collection_date"].apply( lambda x: Week.fromdate( datetime.datetime.strptime( x, "%Y-%m-%d" ).date() ).startdate() )
    md["collection_date"] = pd.to_datetime( md["collection_date"], format="%Y-%m-%d" ).dt.normalize()
    md["days_past"] = ( md["collection_date"].max() - md["collection_date"] ).dt.days

    md["originating_lab"] = md["originating_lab"].replace( { 'UC San Diego Center for Advanced Laboratory Medicine' :  "UCSD CALM Lab",
                                                            "UCSD EXCITE" : "UCSD EXCITE Lab",
                                                            "EXCITE Lab" : "UCSD EXCITE Lab",
                                                            "Andersen lab at Scripps Research" : "SD County Public Health Laboratory",
                                                            "San Diego County Public Health Laboratory" : "SD County Public Health Laboratory",
                                                            "Sharp HealthCare Laboratory" : "Sharp Health",
                                                            "Scripps Medical Laboratory" : "Scripps Health",
                                                            "Rady Children's Hospital - San Diego" : "Rady Children's Hospital",
                                                            "Rady Children’s Hospital" : "Rady Children's Hospital"} )

    excite_providers = load_excite_providers()

    # Correct some sequencer problems
    md["sequencer"] = "Andersen Lab"
    md.loc[md["originating_lab"]=="UCSD EXCITE Lab","sequencer"] = "UCSD EXCITE Lab"
    md.loc[md["authors"]=="Helix","sequencer"] = "Helix"
    md.loc[md["ID"].isin( load_file_as_list( "resources/sdphl_sequences.txt" ) ),"sequencer"] = "SD County Public Health Laboratory"
    md.loc[md['ID'].str.startswith( "CA-SDCPHL-" ),"sequencer"] = "SD County Public Health Laboratory"

    md["provider"] = md["originating_lab"]
    md.loc[md["originating_lab"]=="UCSD EXCITE Lab", "provider"] = md["ID"].map( excite_providers )
    md["provider"] = md["provider"].replace( {"RTL" : "UCSD Return to Learn",
                                             "CALM" : "UCSD CALM Lab",
                                             "HELIX" : "Helix",
                                             "San Diego Fire-Rescue Department" : "SD Fire-Rescue Department",
                                             "SASEA" : "UCSD Safer at School Early Action",
                                             "Instituto de Diagnostico y Referencia Epidemiologicos (InDRE)": "InDRE",
                                             "Delta" : "Helix",
                                              "DeltaAmplicon" : "Helix"} )
    md.loc[md["provider"].isna(),"provider"] = md["sequencer"]

    # Add pangolin lineage information
    pango_loc = "https://raw.githubusercontent.com/andersen-lab/HCoV-19-Genomics/master/lineage_report.csv"
    pango = pd.read_csv( pango_loc, usecols=["taxon", "lineage"] )
    pango["num"] = pango["taxon"].str.extract( "SEARCH-([0-9]+)" )
    pango.loc[pango["num"].isna(),"num"] = pango["taxon"]
    pango = pango[["num", "lineage"]]


    md["num"] = md["ID"].str.extract( "SEARCH-([0-9]+)" )
    md.loc[md["num"].isna(),"num"] = md["ID"]


    md = md.merge( pango, left_on="num", right_on="num", how="left", validate="one_to_one" )

    # Filter sequences which failed lineage calling. These sequences are likely incomplete/erroneous.
    md = md.loc[md["lineage"]!="None"]

    md = md[["ID","collection_date", "zipcode", "epiweek", "days_past", "sequencer", "provider", "lineage", "state"]]

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
    sd = download_sd_cases()
    bc = download_bc_cases()
    c = pd.concat( [sd,bc] )

    return c

def download_sd_cases():
    """
    Returns
    -------
    pandas.DataFrame
        DataFrame detailing the daily number of cases in San Diego.
    """
    def _append_population( dataframe ):
        pop_loc = "resources/zip_pop.csv"
        pop = pd.read_csv( pop_loc )
        pop = pop.set_index( "Zip" )
        pop["Total Population"] = pd.to_numeric( pop["Total Population"].str.replace( ",", "" ) )
        pop = pop["Total Population"].to_dict()
        dataframe["population"] = dataframe["ziptext"].map( pop )
        return dataframe

    def _add_missing_cases( entry ):
        entry = entry.set_index( "updatedate" ).reindex( pd.date_range( entry["updatedate"].min(), entry["updatedate"].max() ) ).rename_axis( "updatedate" ).reset_index()
        indexer = pd.api.indexers.FixedForwardWindowIndexer(window_size=7)
        entry["new_cases"] = entry.rolling( window=indexer, min_periods=1 )["new_cases"].apply( lambda x: x.max() / 7 )
        return entry

    cases_loc = "https://opendata.arcgis.com/datasets/8fea64744565407cbc56288ab92f6706_0.geojson"
    sd = gpd.read_file( cases_loc )
    sd = sd[["ziptext","case_count", "updatedate"]]
    sd["updatedate"] = pd.to_datetime( sd["updatedate"] ).dt.tz_localize( None )
    sd["updatedate"] = sd["updatedate"].dt.normalize()
    sd["ziptext"] = pd.to_numeric( sd["ziptext"] )
    sd = sd.groupby( ["updatedate", "ziptext"] ).last().reset_index()
    sd = sd.sort_values( "updatedate" )

    # Calculate cases per day because thats way more useable than cummulative counts.
    sd = _append_population( sd )
    sd["case_count"] = sd["case_count"].fillna( 0 )
    sd["new_cases"] = sd.groupby( "ziptext" )["case_count"].diff()
    sd["new_cases"] = sd["new_cases"].fillna( sd["case_count"] )
    sd.loc[sd["new_cases"]<0, "new_cases"] = 0

    # Brief hack because SD stopped reporting daily cases and instead reports weekly cases after 2021-06-29.
    sdprob = sd.loc[sd["updatedate"]>"2021-06-28"]
    sdprob = sdprob.groupby( "ziptext" ).apply( _add_missing_cases )
    sdprob = sdprob.drop( columns="ziptext" ).reset_index()
    sdprob = sdprob.drop( columns="level_1" )

    sd = sd.loc[sd["updatedate"]<="2021-06-28"]
    sd = pd.concat( [sd,sdprob] )

    sd["days_past"] = ( datetime.datetime.today() - sd["updatedate"] ).dt.days

    sd["case_count"] = sd.groupby( "ziptext" )["new_cases"].cumsum()
    return sd

def download_bc_cases():
    """
    Returns
    -------
    pandas.DataFrame
        DateFrame detailing the daily number of cases in Baja California, Mexico
    """
    # This heuristic works for today, so hopefully it works for other days.
    today = datetime.datetime.today()
    date_url = int( today.strftime( "%Y%m%d" ) ) - 1
    bc_url = f"https://datos.covid-19.conacyt.mx/Downloads/Files/Casos_Diarios_Estado_Nacional_Confirmados_{date_url}.csv"

    # Load and format the data from the url
    bc = pd.read_csv( bc_url, index_col="nombre" )
    bc = bc.drop( columns=["cve_ent", "poblacion"] )
    bc = bc.T
    bc = bc["BAJA CALIFORNIA"].reset_index()
    bc["index"] = pd.to_datetime( bc["index"], format="%d-%m-%Y" ).dt.tz_localize( None )
    bc["index"] = bc["index"].dt.normalize()
    bc.columns = ["updatedate", "new_cases"]
    bc = bc.sort_values( "updatedate" )

    # Generate the additional columns
    bc["case_count"] = bc["new_cases"].cumsum()
    bc["ziptext"] = "None"
    bc["population"] = 3648100
    bc["days_past"] = ( today - bc["updatedate"] ).dt.days

    bc = bc.loc[bc["case_count"] > 0]

    return bc

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

def estimate_sgtf():
    # Function representing the logistic growth model
    def lgm( ndays, x0, r ):
        return 1 / ( 1 + ( ( ( 1 / x0 ) - 1 ) * exp( -1 * r * ndays ) ) )

    tests = pd.read_csv( "https://raw.githubusercontent.com/andersen-lab/SARS-CoV-2_SGTF_San-Diego/main/SGTF_San_Diego.csv", parse_dates=["Collection date"] )
    tests.columns = ["Date", "sgtf_likely", "total_positive", "percent"]
    tests["percent"] = tests["sgtf_likely"] / tests["total_positive"]
    tests["percent_filter"] = savgol_filter( tests["percent"], window_length=5, polyorder=2 )
    tests["ndays"] = tests.index

    fit, covar = curve_fit( lgm, tests["ndays"], tests["percent_filter"], [0.001, 0.008] )
    sigma_ab = sqrt( diagonal( covar ) )

    days_sim = 300

    fit_df = pd.DataFrame( {"date" : pd.date_range( tests["Date"].min(), periods=days_sim ) } )
    fit_df["ndays"] = fit_df.index
    fit_df["fit_y"] = [lgm(i, fit[0], fit[1]) for i in range( days_sim )]
    fit_df["fit_lower"] = [lgm(i, fit[0]-sigma_ab[0], fit[1]-sigma_ab[1]) for i in range( days_sim )]
    fit_df["fit_upper"] = [lgm(i, fit[0]+sigma_ab[0], max(0, fit[1]+sigma_ab[1]) ) for i in range( days_sim )]

    above_50 = fit_df.loc[fit_df["fit_y"] >= 0.5,"date"].min()
    above_50_lower = fit_df.loc[fit_df["fit_lower"] >= 0.5,"date"].min()
    above_50_upper = fit_df.loc[fit_df["fit_upper"] >= 0.5,"date"].min()

    growth_rate = fit[1]
    serial_interval = 5.5

    estimates = pd.DataFrame( {
        "estimate" : [above_50,growth_rate],
        "lower" : [above_50_lower,growth_rate - sigma_ab[1]],
        "upper" : [above_50_upper,growth_rate + sigma_ab[1]] }, index=["date", "growth_rate"] )
    estimates = estimates.T
    estimates["doubling_time"] = log(2) / estimates["growth_rate"]
    estimates["transmission_increase"] = serial_interval * estimates["growth_rate"]

    tests.to_csv( "resources/tests.csv", index=False )
    fit_df.to_csv( "resources/fit.csv", index=False )
    estimates.to_csv( "resources/estimates.csv" )

if __name__ == "__main__":
    #seqs_md = download_search()
    #seqs_md.to_csv( "resources/sequences.csv", index=False )

    estimate_sgtf()

    #cases = download_cases()
    #cases.to_csv( "resources/cases.csv", index=False )

    #sd_zips = download_shapefile()
    #sd_zips.to_file("resources/zips.geojson", driver='GeoJSON' )
