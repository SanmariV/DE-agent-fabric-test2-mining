select
    data_source.DataSource_BK,
    data_source.SourceName,
    data_source.SourceUrl
from {{ ref('dbo.DataSource') }} as data_source
