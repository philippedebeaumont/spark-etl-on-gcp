import argparse
import logging
from pyspark.sql import SparkSession
from pyspark.sql.functions import concat, col, lit, to_timestamp, to_date, sum, count, max
from pyspark.sql.types import IntegerType, FloatType

def get_station_location(df, df_station, start_or_end):
    if start_or_end == "start":
        left_key = "StartStation Id"
        column_location_name = "start_location"
    elif start_or_end == "end":
        left_key = "EndStation Id"
        column_location_name = "end_location"
    
    df = df.join(df_station, [df[left_key] == df_station["id"]])
    df = df.withColumn(column_location_name, concat(col("latitude"), lit(", "), col("longitude")))
    df = df.drop(*["id", "latitude", "longitude"])
    return df

def format_datetime(df, column_name):
    df = df.withColumn(column_name, to_timestamp(df[column_name], "dd/MM/yyyy HH:mm"))
    return df

def df_preparation_to_bq(df):
    df = df.withColumnRenamed("Rental Id", "rental_id").withColumnRenamed("Duration", "duration") \
        .withColumnRenamed("Bike Id", "bike_id").withColumnRenamed("End Date", "end_date") \
        .withColumnRenamed("EndStation Id", "end_station_id").withColumnRenamed("EndStation Name", "end_station_name") \
        .withColumnRenamed("Start Date", "start_date").withColumnRenamed("StartStation Id", "start_station_id") \
        .withColumnRenamed("StartStation Name", "start_station_name")
    df = df.select("rental_id", "duration", "bike_id", "start_date", "start_station_id", "start_station_name", "start_location",
                "end_date", "end_station_id", "end_station_name", "end_location")
    return df

def load_to_bq(df, project_id, dest_table):
    df.write.format("bigquery") \
        .option("table", project_id + "." + dest_table) \
        .mode("append") \
        .save()

def get_daily_agg(df):
    df = df.withColumn("start_date", to_date(col("start_date")))
    df = df.withColumn("end_date", to_date(col("end_date")))
    df = df.groupBy("start_date", "start_station_id").agg(
        max("start_station_name").alias("start_station_name"),
        max("start_location").alias("start_location"),
        sum("duration").alias("total_duration"),
        count("rental_id").alias("hire_count")
    )
    return df

def get_datetime_weather(df):
    df = df.withColumn("date", to_timestamp(df["date"], "yyyy-MM-dd"))
    df = df.withColumn("date", to_date(col("date")))
    return df

def get_weather_data(df, df_weather):
    df = df.join(df_weather, [df["start_date"] == df_weather["date"]])
    df = df.drop("date")
    return df

def run():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--bucket',
        dest='bucket',
        help='Bucket on cloud storage.')
    parser.add_argument(
        '--input_file',
        dest='input_file',
        help='Input csv file to process.')
    parser.add_argument(
        '--station_data',
        dest='station_data',
        help='Station data to process.')
    parser.add_argument(
        '--weather_data',
        dest='weather_data',
        help='Weather data to process.')
    parser.add_argument(
        '--project',
        dest='project',
        help='Project id to use.')
    parser.add_argument(
        '--table_hires',
        dest='table_hires',
        help='Output table to write hires results to.')
    parser.add_argument(
        '--table_daily_agg',
        dest='table_daily_agg',
        help='Output table to write daily agg results to.')
    
    args = parser.parse_args()

    spark = SparkSession.builder.appName("Spark Dataframes")\
        .config("spark.driver.extraJavaOptions", "-Dorg.slf4j.simpleLogger.defaultLogLevel=WARN") \
        .config("spark.executor.extraJavaOptions", "-Dorg.slf4j.simpleLogger.defaultLogLevel=WARN") \
        .getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    spark.conf.set('temporaryGcsBucket', args.bucket)

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info(f'Beginning treatment of file {args.input_file}')

    df_station = spark.read.option("header", True).csv(args.station_data).select("id", "latitude", "longitude")
    df_weather = spark.read.option("header", True).csv(args.weather_data)
    df_weather = df_weather.withColumn("prcp", df_weather["prcp"].cast(FloatType()))
    df_weather = df_weather.withColumn("tavg", df_weather["tavg"].cast(FloatType()))
    df = spark.read.option("header", True).csv(args.input_file)
    df = df.withColumn("Duration", df["Duration"].cast(IntegerType()))
    df = get_station_location(df, df_station, "start")
    df = get_station_location(df, df_station, "end")
    df = format_datetime(df, "Start Date")
    df = format_datetime(df, "End Date")
    
    df = df_preparation_to_bq(df)
    load_to_bq(df, args.project, args.table_hires)

    df_daily_agg = get_daily_agg(df)

    df_weather = get_datetime_weather(df_weather)
    df_daily_agg = get_weather_data(df_daily_agg, df_weather)

    load_to_bq(df_daily_agg, args.project, args.table_daily_agg)
    logging.info(f'Ended treatment of file {args.input_file}')
  
    spark.stop()

if __name__ == '__main__':
    run()
