with

processing as (

    select * from {{ ref('dbo.FacilityProcessing') }}

),

facility as (

    select * from {{ ref('facilities.DimFacility') }}

),

data_source as (

    select * from {{ ref('facilities.DimDataSource') }}

)

select
    processing.FacilityProcessing_BK,
    coalesce(facility.DimFacility_SK, -1) as DimFacility_SK,
    coalesce(data_source.DimDataSource_SK, -1) as DimDataSource_SK,
    processing.FacilityType,
    processing.InputMaterial,
    processing.OutputMaterial,
    processing.ReportingPeriod,
    processing.HasPurchasedMaterial,
    processing.ReportingYear,
    processing.InputValueTonnes,
    processing.OutputValueTonnes,
    processing.GradePartsPerMillion,
    processing.RecoveryRate,
    processing.AmountSoldTonnes,
    processing.MetalPayableTonnes
from processing
left join facility
    on facility.Facility_BK = processing.Facility_BK
left join data_source
    on data_source.DataSource_BK = processing.DataSource_BK
