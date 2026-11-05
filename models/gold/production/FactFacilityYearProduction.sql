with

facility_year as (

    select * from {{ ref('production.FacilityYearProduction') }}

),

facility as (

    select * from {{ ref('facilities.DimFacility') }}

)

select
    facility_year.FacilityYear_BK,
    coalesce(facility.DimFacility_SK, -1) as DimFacility_SK,
    facility_year.ReportingYear,
    facility_year.OreMinedTonnes,
    facility_year.OreProcessedTonnes,
    facility_year.ConcentrateTonnes,
    facility_year.WasteTonnes
from facility_year
left join facility
    on facility.Facility_BK = facility_year.Facility_BK
