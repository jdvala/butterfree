"""Holds the Online Feature Store writer class."""

import os
from typing import Any, Dict, List, Union

from pyspark.sql import DataFrame
from pyspark.sql.streaming import StreamingQuery

from butterfree.clients import SparkClient
from butterfree.configs.db import AbstractWriteConfig, CassandraConfig
from butterfree.load.writers.writer import Writer
from butterfree.transform import FeatureSet


class CassandraWriter(Writer):
    """Enable writing feature sets into the Online Feature Store.

    Attributes:
        db_config: Spark configuration for connect databases.
            For more information check the module 'butterfree.db.configs'.
        debug_mode: "dry run" mode, write the result to a temporary view.
        write_to_entity: option to write the data to the entity table.
            With this option set to True, the writer will write the feature set to
            a table with the name equal to the entity name, defined on the pipeline.
            So, it WILL NOT write to a table with the name of the feature set, as it
            normally does.

    Example:
        Simple example regarding OnlineFeatureStoreWriter class instantiation.
        We can instantiate this class without db configurations, so the class get the
        CassandraConfig() where it provides default configurations about CassandraDB.

    >>> spark_client = SparkClient()
    >>> writer = OnlineFeatureStoreWriter()
    >>> writer.write(feature_set=feature_set,
       ...           dataframe=dataframe,
       ...           spark_client=spark_client)

        However, we can define the db configurations and provide them to
        OnlineFeatureStoreWriter.

    >>> spark_client = SparkClient()
    >>> config = CassandraConfig(mode="overwrite",
        ...                      format_="parquet",
        ...                      keyspace="keyspace_name")

    >>> writer = OnlineFeatureStoreWriter(db_config=config)
    >>> writer.write(feature_set=feature_set,
       ...           dataframe=dataframe,
       ...           spark_client=spark_client)

        For what settings you can use on CassandraConfig and default settings,
        to read CassandraConfig class.

        We can instantiate OnlineFeatureStoreWriter class to validate the writers,
        using the default or custom configs.

    >>> spark_client = SparkClient()
    >>> writer = OnlineFeatureStoreWriter()
    >>> writer.validate(feature_set=feature_set,
       ...              dataframe=dataframe,
       ...              spark_client=spark_client)

        Both methods (writer and validate) will need the Spark Client,
        Feature Set and DataFrame, to write or to validate,
        according to OnlineFeatureStoreWriter class arguments.
    """

    __name__ = "Cassandra Writer"

    def __init__(
        self,
        db_config: Union[AbstractWriteConfig, CassandraConfig] = None,
        debug_mode: bool = False,
        write_to_entity: bool = False,
    ):
        super(CassandraWriter, self).__init__()
        self.db_config = db_config or CassandraConfig()
        self.debug_mode = debug_mode
        self.write_to_entity = write_to_entity

    def _write_stream(
        self,
        feature_set: FeatureSet,
        dataframe: DataFrame,
        spark_client: SparkClient,
        table_name: str,
    ) -> StreamingQuery:
        """Writes the dataframe in streaming mode."""
        checkpoint_folder = (
            f"{feature_set.name}__on_entity" if self.write_to_entity else table_name
        )
        checkpoint_path = (
            os.path.join(
                self.db_config.stream_checkpoint_path,
                feature_set.entity,
                checkpoint_folder,
            )
            if self.db_config.stream_checkpoint_path
            else None
        )
        streaming_handler = spark_client.write_stream(
            dataframe,
            processing_time=self.db_config.stream_processing_time,
            output_mode=self.db_config.stream_output_mode,
            checkpoint_path=checkpoint_path,
            format_=self.db_config.format_,
            mode=self.db_config.mode,
            **self.db_config.get_options(table_name),
        )
        return streaming_handler

    @staticmethod
    def _write_in_debug_mode(
        table_name: str, dataframe: DataFrame, spark_client: SparkClient
    ) -> Union[StreamingQuery, None]:
        """Creates a temporary table instead of writing to the real feature store."""
        return spark_client.create_temporary_view(
            dataframe=dataframe, name=f"online_feature_store__{table_name}"
        )

    def write(
        self, feature_set: FeatureSet, dataframe: DataFrame, spark_client: SparkClient,
    ) -> Union[StreamingQuery, None]:
        """Loads the latest data from a feature set into the Feature Store.

        Args:
            feature_set: object processed with feature set metadata.
            dataframe: Spark dataframe containing data from a feature set.
            spark_client: client for Spark connections with external services.

        Returns:
            Streaming handler if writing streaming df, None otherwise.

        If the debug_mode is set to True, a temporary table with a name in the format:
        `online_feature_store__my_feature_set` will be created instead of writing to
        the real online feature store. If dataframe is streaming this temporary table
        will be updated in real time.

        """
        table_name = feature_set.entity if self.write_to_entity else feature_set.name

        if dataframe.isStreaming:
            dataframe = self._apply_transformations(dataframe)
            if self.debug_mode:
                return self._write_in_debug_mode(
                    table_name=table_name,
                    dataframe=dataframe,
                    spark_client=spark_client,
                )
            return self._write_stream(
                feature_set=feature_set,
                dataframe=dataframe,
                spark_client=spark_client,
                table_name=table_name,
            )

        dataframe = self._apply_transformations(df=dataframe)

        if self.debug_mode:
            return self._write_in_debug_mode(
                table_name=table_name, dataframe=dataframe, spark_client=spark_client
            )

        return spark_client.write_dataframe(
            dataframe=dataframe,
            format_=self.db_config.format_,
            mode=self.db_config.mode,
            **self.db_config.get_options(table_name),
        )

    def validate(
        self, feature_set: FeatureSet, dataframe: DataFrame, spark_client: SparkClient
    ) -> None:
        """Calculate dataframe rows to validate data into Feature Store.

        Args:
            feature_set: object processed with feature set metadata.
            dataframe: Spark dataframe containing data from a feature set.
            spark_client: client for Spark connections with external services.

        Raises:
            AssertionError: if validation fails.

        """
        # validation with online feature store can be done right now, since
        # this database can be updated by an streaming job while our ETL is running
        # therefore, creating in consistencies between this ETL feature set count and
        # the data already written to the FS.
        # TODO how to run data validations when a database has concurrent writes.
        pass

    def get_db_schema(self, feature_set: FeatureSet) -> List[Dict[Any, Any]]:
        """Get desired database schema.

        Args:
            feature_set: object processed with feature set metadata.

        Returns:
            Desired database schema.

        """
        db_schema = self.db_config.translate(feature_set.get_schema())
        return db_schema