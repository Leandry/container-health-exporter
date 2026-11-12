# Gunicorn loads this file from its working directory (/app in the image).

# Two threads, so that /healthz still answers while a scrape is in progress.
threads = 2

# Keep the worker heartbeat file in memory: no write to the root filesystem,
# so the container also runs with a read-only root filesystem.
worker_tmp_dir = '/dev/shm'

# The control socket is not used and would need a writable home directory.
control_socket_disable = True
