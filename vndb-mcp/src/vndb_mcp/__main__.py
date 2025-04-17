"""Main entry point for the VNDB MCP server.
This revised version includes cross-platform signal handling and modern asyncio patterns.
"""
import asyncio
import signal
import sys
import logging
import platform
from vndb_mcp.main import main as main_func

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def shutdown(signal_obj, loop):
    """Function to handle shutdown sequence
    
    Cancels all running tasks and safely stops the event loop.
    """
    logger.info(f"Received exit signal {signal_obj.name if hasattr(signal_obj, 'name') else signal_obj}...")
    
    # Get all tasks except the current task
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    
    if tasks:
        logger.info(f"Cancelling {len(tasks)} outstanding tasks")
        # Cancel all tasks
        for task in tasks:
            task.cancel()
        
        # Wait for completion of canceled tasks
        await asyncio.gather(*tasks, return_exceptions=True)
    
    # Stop the event loop if it's running
    if loop.is_running():
        loop.stop()

async def main():
    """Main asynchronous function.
    
    Implements main processing including exception handling.
    """
    try:
        logger.info("Starting VNDB MCP server")
        await main_func()
        return 0
    except Exception as e:
        logger.error(f"Error in main function: {e}", exc_info=True)
        return 1

def run():
    """Run the server.
    
    Performs platform-specific signal handling and error management.
    """
    # Create a new event loop (avoiding deprecated get_event_loop)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Platform-specific signal handling
    if platform.system() != 'Windows':
        # Signal handlers for UNIX systems
        logger.info("Setting up UNIX signal handlers")
        for s in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                s, lambda s=s: asyncio.create_task(shutdown(s, loop))
            )
    else:
        # On Windows, add_signal_handler is not supported,
        # so KeyboardInterrupt is caught with a try-except block
        logger.info("Running on Windows, using alternative signal handling")
    
    exit_code = 1
    try:
        # Use run_until_complete instead of asyncio.run
        # This ensures compatibility with signal handling
        exit_code = loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        # Cleanup process for Windows
        loop.run_until_complete(shutdown("SIGINT (Ctrl+C)", loop))
        exit_code = 0
    finally:
        # Check for tasks remaining in the event loop
        pending = asyncio.all_tasks(loop)
        if pending:
            logger.info(f"Cleaning up {len(pending)} pending tasks...")
            # Cancel and wait for completion of remaining tasks
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        
        logger.info("Shutting down event loop")
        loop.close()
    
    return exit_code

# Alternative implementation (latest asyncio pattern)
def run_modern():
    """Alternative function to run the server with modern asyncio patterns.
    
    This version uses `asyncio.run()` and is more concise, but
    doesn't perform detailed signal handling or Shutdown control.
    """
    try:
        return asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
        return 0

if __name__ == "__main__":
    # Default execution method
    sys.exit(run())
    
    # If you want to use modern asyncio patterns, comment out the line above
    # and uncomment the following line
    # sys.exit(run_modern())

# Export to make it accessible from scripts
main_entry = run  # Changed from the old main = run to avoid name conflicts
