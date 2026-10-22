"""
Query Executor - Unified database query execution logic.
"""

from typing import Optional, List, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor


class QueryExecutor:
    """
    Unified query execution logic for all databases.
    Handles connection management and result formatting.
    """

    def __init__(self, connection_url: str, default_limit: int = 5):
        self.connection_url = connection_url
        self.default_limit = default_limit

    def get_connection(self):
        """Create and return a new database connection."""
        if not self.connection_url:
            raise ValueError("Database connection URL is not configured")
        return psycopg2.connect(self.connection_url)

    def execute_query(self, sql: str, parameters: Optional[List] = None) -> str:
        """
        Execute SQL query and return formatted results.

        Args:
            sql: SQL query string
            parameters: Optional list of query parameters

        Returns:
            Formatted string with query results
        """
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Build query string with parameters
                if parameters:
                    query_string = cur.mogrify(sql, parameters).decode('utf-8')
                else:
                    query_string = sql

                cur.execute(query_string)

                # Check if this is a SELECT query
                if cur.description is None:
                    conn.commit()
                    return f"Query executed successfully. Rows affected: {cur.rowcount}"

                # Fetch results
                rows = cur.fetchmany(self.default_limit)
                if not rows:
                    return "Query executed successfully, but returned no data."

                return self._format_results(rows, cur.rowcount)

        except psycopg2.Error as e:
            return f"Database error: {str(e)}"
        except Exception as e:
            return f"Query error: {str(e)}"
        finally:
            if conn:
                conn.close()

    def _format_results(self, rows: List[Dict], total_count: int) -> str:
        """
        Format query results as human-readable string.

        Args:
            rows: List of row dictionaries
            total_count: Total number of rows in result

        Returns:
            Formatted string with results
        """
        result_lines = []

        for row in rows:
            line_items = []
            for key, val in row.items():
                formatted_val = self._format_value(val)
                line_items.append(f"{key}: {formatted_val}")
            result_lines.append(" | ".join(line_items))

        output = "\n".join(result_lines)

        if total_count > len(rows):
            output += f"\n\n(Showing {len(rows)} of {total_count} total rows)"

        return output

    def _format_value(self, val: Any) -> str:
        """
        Format a single value for display.

        Args:
            val: Value to format

        Returns:
            Formatted string representation
        """
        if val is None:
            return "NULL"
        elif isinstance(val, (bytes, bytearray)):
            return val.decode('utf-8', errors='replace')
        else:
            return str(val).replace('%', '%%')

    def execute_for_csv(self, sql: str, parameters: Optional[List] = None,
                        batch_size: int = 10000):
        """
        Execute query and yield results in batches for CSV export.

        Args:
            sql: SQL query string
            parameters: Optional query parameters
            batch_size: Number of rows per batch

        Yields:
            Tuple of (column_names, batch_rows) for first batch,
            then (None, batch_rows) for subsequent batches
        """
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                # Set array size for efficient batch fetching
                cur.arraysize = batch_size

                # Build and execute query
                if parameters:
                    query_string = cur.mogrify(sql, parameters).decode('utf-8')
                else:
                    query_string = sql

                cur.execute(query_string)

                # Check if this is a SELECT query
                if cur.description is None:
                    raise ValueError("Query does not return results (not a SELECT query)")

                # Get column names
                column_names = [desc[0] for desc in cur.description]

                # Yield batches
                first_batch = True
                while True:
                    batch = cur.fetchmany(batch_size)
                    if not batch:
                        break

                    # Convert tuples to dicts
                    batch_dicts = []
                    for row_tuple in batch:
                        row_dict = dict(zip(column_names, row_tuple))
                        # Clean values
                        cleaned_row = {}
                        for key, val in row_dict.items():
                            cleaned_row[key] = self._clean_value_for_csv(val)
                        batch_dicts.append(cleaned_row)

                    if first_batch:
                        yield (column_names, batch_dicts)
                        first_batch = False
                    else:
                        yield (None, batch_dicts)

        finally:
            if conn:
                conn.close()

    def _clean_value_for_csv(self, val: Any) -> Any:
        """
        Clean a value for CSV export.

        Args:
            val: Value to clean

        Returns:
            Cleaned value suitable for CSV
        """
        if val is None:
            return ""
        elif isinstance(val, (bytes, bytearray)):
            return val.decode('utf-8', errors='replace')
        else:
            return val
