"""Background task management for provisioning workflows.

Manages long-running background threads that perform periodic checks
(e.g., GitHub invitation status) without blocking the chat bot.
"""
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)


class BackgroundTaskManager:
    """Manages background tasks with periodic execution."""
    
    def __init__(self):
        self.tasks: dict = {}  # {task_name: thread}
        self.running = False
    
    def start_github_check_thread(self, interval_seconds: int):
        """Start the GitHub invitation check background thread.
        
        Args:
            interval_seconds: Check interval in seconds (e.g., 300 for 5 minutes)
        """
        if 'github_check' in self.tasks:
            logger.warning("GitHub check thread already running")
            return
        
        logger.info(f"Starting GitHub background check thread (interval: {interval_seconds}s)")
        
        def _github_check_loop():
            from backend.github_provisioning import check_github_invitations
            
            while self.running:
                try:
                    results = check_github_invitations()
                    if results['accepted_and_assigned'] or results['failed'] or results['errors']:
                        logger.info(f"GitHub check: {results['accepted_and_assigned']} assigned, "
                                   f"{len(results['failed'])} failed, {len(results['errors'])} errors")
                except Exception as e:
                    logger.exception(f"Unexpected error in GitHub check thread: {e}")
                
                # Sleep in small intervals so we can stop quickly
                for _ in range(interval_seconds):
                    if not self.running:
                        break
                    time.sleep(1)
        
        thread = threading.Thread(target=_github_check_loop, daemon=True, name='github_check_background')
        thread.start()
        self.tasks['github_check'] = thread
    
    def start_all(self):
        """Start all configured background tasks."""
        self.running = True
        
        # GitHub background check
        if 'GITHUB_BACKGROUND_CHECK_INTERVAL' in os.environ:
            try:
                interval = int(os.environ['GITHUB_BACKGROUND_CHECK_INTERVAL'])
                self.start_github_check_thread(interval)
            except (ValueError, Exception) as e:
                logger.error(f"Failed to start GitHub check thread: {e}")
    
    def stop_all(self):
        """Stop all background tasks."""
        logger.info("Stopping background tasks")
        self.running = False
        for task_name, thread in self.tasks.items():
            logger.debug(f"Waiting for {task_name} to finish...")
            thread.join(timeout=5)


# Global task manager instance
_task_manager = BackgroundTaskManager()


def init_background_tasks():
    """Initialize and start all background tasks."""
    _task_manager.start_all()


def shutdown_background_tasks():
    """Stop all background tasks gracefully."""
    _task_manager.stop_all()
