with

ownership as (

    select * from {{ ref('dbo.FacilityOwnership') }}

),

facility as (

    select * from {{ ref('facilities.DimFacility') }}

),

data_source as (

    select * from {{ ref('facilities.DimDataSource') }}

)

select
    ownership.FacilityOwnership_BK,
    coalesce(facility.DimFacility_SK, -1) as DimFacility_SK,
    coalesce(data_source.DimDataSource_SK, -1) as DimDataSource_SK,
    ownership.OwnershipYear,
    ownership.Owners,
    ownership.Operators
from ownership
left join facility
    on facility.Facility_BK = ownership.Facility_BK
left join data_source
    on data_source.DataSource_BK = ownership.DataSource_BK
