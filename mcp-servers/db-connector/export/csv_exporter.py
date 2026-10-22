"""
Streaming CSV Exporter - Memory-efficient CSV export with batching.
"""

import csv
import os
import shutil
import tempfile
import traceback
from typing import Optional, List, Callable
from pathlib import Path

from .job_status_manager import create_job, update_job_status


class StreamingCSVExporter:
    """
    Memory-efficient streaming CSV exporter with batch processing.
    Supports automatic file splitting and progress tracking.
    """

    def __init__(self, query_executor_factory: Callable[[], 'QueryExecutor'],
                 default_batch_size: int = 10000,
                 default_max_file_size_mb: int = 1024):
        """
        Initialize exporter.

        Args:
            query_executor_factory: Factory function to create QueryExecutor
            default_batch_size: Default rows per batch
            default_max_file_size_mb: Default max file size before splitting
        """
        self.query_executor_factory = query_executor_factory
        self.default_batch_size = default_batch_size
        self.default_max_file_size_mb = default_max_file_size_mb

    def export(self, job_id: str, sql: str, path: str,
               parameters: Optional[List] = None,
               batch_size: Optional[int] = None,
               max_file_size_mb: Optional[int] = None):
        """
        Export query results to CSV with streaming.

        Args:
            job_id: Job identifier for tracking
            sql: SQL query to execute
            path: Output file path
            parameters: Optional query parameters
            batch_size: Rows per batch (default: 10000)
            max_file_size_mb: Max file size in MB before splitting (default: 1024)
        """
        batch_size = batch_size or self.default_batch_size
        max_file_size_mb = max_file_size_mb or self.default_max_file_size_mb

        temp_file = None
        temp_file_path = None

        try:
            # Create job entry
            create_job(job_id, sql, path)
            update_job_status(job_id, 'starting', 0, 'Starting export...')

            # Validate disk space
            output_dir = Path(path).parent
            output_dir.mkdir(parents=True, exist_ok=True)

            disk_usage = shutil.disk_usage(str(output_dir))
            free_gb = disk_usage.free / (1024 ** 3)
            if free_gb < 1:
                raise IOError(f"Insufficient disk space: {free_gb:.2f}GB free (need at least 1GB)")

            update_job_status(job_id, 'connected', 5, 'Disk space validated, preparing query...')

            # Create query executor
            executor = self.query_executor_factory()

            # Create temporary file
            temp_file = tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.csv',
                delete=False,
                newline='',
                encoding='utf-8'
            )
            temp_file_path = temp_file.name

            update_job_status(job_id, 'executing', 15, 'Executing query...')

            # Track file parts
            part_num = 1
            part_paths = []
            current_file_size_bytes = 0
            max_file_size_bytes = max_file_size_mb * 1024 * 1024
            total_rows = 0
            csv_writer = None
            fieldnames = None

            # Process batches
            for batch_result in executor.execute_for_csv(sql, parameters, batch_size):
                columns, batch_rows = batch_result

                # Initialize CSV writer on first batch
                if columns is not None:
                    fieldnames = columns
                    csv_writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
                    csv_writer.writeheader()
                    update_job_status(job_id, 'processing', 25, f'Writing data (batch size: {batch_size})...')

                # Write rows
                for row in batch_rows:
                    csv_writer.writerow(row)
                    total_rows += 1

                # Check file size
                temp_file.flush()
                current_file_size_bytes = os.path.getsize(temp_file_path)
                current_file_size_mb = current_file_size_bytes / (1024 * 1024)

                # Progress update
                progress = min(25 + int((total_rows / max(total_rows + batch_size, 1)) * 65), 90)
                update_job_status(
                    job_id, 'processing', progress,
                    f'Processed {total_rows} rows ({current_file_size_mb:.1f}MB)...'
                )

                # Check if need to split file
                if max_file_size_mb > 0 and current_file_size_bytes > max_file_size_bytes:
                    temp_file.close()

                    # Move to part file
                    part_path = f"{path}.part{part_num}"
                    shutil.move(temp_file_path, part_path)
                    part_paths.append(part_path)

                    update_job_status(
                        job_id, 'splitting', progress,
                        f'Created part {part_num} ({current_file_size_mb:.1f}MB), continuing...'
                    )

                    part_num += 1

                    # Create new temp file
                    temp_file = tempfile.NamedTemporaryFile(
                        mode='w',
                        suffix='.csv',
                        delete=False,
                        newline='',
                        encoding='utf-8'
                    )
                    temp_file_path = temp_file.name
                    csv_writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
                    csv_writer.writeheader()
                    current_file_size_bytes = 0

            # Finalize
            if temp_file and not temp_file.closed:
                temp_file.close()

            update_job_status(job_id, 'finalizing', 95, 'Finalizing export...')

            # Handle final file
            if part_paths:
                # Multi-part export
                final_file_size = os.path.getsize(temp_file_path)
                if final_file_size > 0:
                    part_path = f"{path}.part{part_num}"
                    shutil.move(temp_file_path, part_path)
                    part_paths.append(part_path)
                else:
                    os.unlink(temp_file_path)

                # Create info file
                total_size_mb = sum(os.path.getsize(p) for p in part_paths) / (1024 * 1024)
                info_path = f"{path}_split_into_{len(part_paths)}_parts"
                with open(info_path, 'w') as f:
                    f.write(f"Total rows: {total_rows}\n")
                    f.write(f"Total size: {total_size_mb:.2f}MB\n")
                    f.write(f"Parts:\n")
                    for p in part_paths:
                        f.write(f"  - {p}\n")

                update_job_status(
                    job_id, 'completed', 100,
                    f'Export completed: {total_rows} rows, {len(part_paths)} files ({total_size_mb:.1f}MB total)'
                )
            else:
                # Single file export
                shutil.move(temp_file_path, path)
                file_size_mb = os.path.getsize(path) / (1024 * 1024)

                update_job_status(
                    job_id, 'completed', 100,
                    f'Export completed: {total_rows} rows ({file_size_mb:.1f}MB) -> {path}'
                )

        except Exception as e:
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            update_job_status(job_id, 'failed', -1, 'Export failed', error_msg)

            # Cleanup temp file on error
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except:
                    pass

            raise
