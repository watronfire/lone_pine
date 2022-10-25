import pandas as pd
from epiweeks import Week
import datetime

def load_excite_providers() :
    excite = pd.read_csv( "resources/excite_providers.csv" )
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
    md = pd.read_csv( search_md, usecols=["ID", "collection_date", "location", "authors", "originating_lab", "zipcode", "host", "percent_coverage_cds"] )
    md["collection_date"] = md["collection_date"].astype( str )

    # Filter out incorrect samples or wastewater
    md = md.loc[~md["ID"].isin(["SEARCH-104076", "SEARCH-58367"])]
    #md = md.loc[~md["ID"].isin( load_file_as_list( "resources/ignore.txt") )]

    md = md.loc[(md["location"]=="North America/USA/California/San Diego")|(md["location"].str.startswith( "North America/Mexico/Baja California" ))]

    md = md.loc[~md["collection_date"].str.startswith( "19" )]
    md = md.loc[~md["collection_date"].str.contains( "/" )]

    md = md.loc[~md["collection_date"].isin( ["NaT", "nan", 'Unknown', 'missing'] )]

    md = md.loc[~md["host"].isin(["Environment","Environmental"] )]

    # Generate an identifiable location column
    md["state"] = "Baja California"
    md.loc[md["location"]=="North America/USA/California/San Diego","state"] = "San Diego"

    #clean up zipcode
    md["zipcode"] = md["zipcode"].astype( "str" )
    md["zipcode"] = md["zipcode"].apply( lambda x: x.split( "-" )[0] )
    # Will covert all zipcodes to int except those with alphabetical characters.
    md["zipcode"] = pd.to_numeric( md["zipcode"], errors="coerce", downcast="integer" )

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
                                             "DeltaAmplicon" : "Helix",
                                             "Genomica Lab Molecular, Mexico" : "Genomica Laboratorio",
                                             "Genomica Lab Molecular, México" : "Genomica Laboratorio"} )
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
    md = md.loc[~md["lineage"].isin( ["None", "Unassigned"] )]

    md = md[["ID","collection_date", "zipcode", "epiweek", "days_past", "sequencer", "provider", "lineage", "state"]]

    return md

if __name__ == "__main__":
    seqs_md = download_search()
    seqs_md.to_csv( "resources/sequences.csv", index=False )
