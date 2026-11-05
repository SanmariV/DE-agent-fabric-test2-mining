-- Most frequent values of one dimension column, from the first
-- $sample_rows rows. Feeds the "Data Example" column. Never run for columns
-- tagged PII; the script skips them before this template is rendered.
-- Parameters: $relation, $column, $sample_rows, $max_examples
with

sampled as (

    select top ($sample_rows) $column as value
    from $relation
    where $column is not null

),

counted as (

    select
        cast(value as varchar(200)) as example_value,
        count(*) as row_count
    from sampled
    group by cast(value as varchar(200))

)

select top ($max_examples) example_value
from counted
order by row_count desc, example_value
