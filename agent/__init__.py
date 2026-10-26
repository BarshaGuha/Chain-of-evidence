"""Chain of Evidence: a multi-agent system that explains why a stockout happened."""
import warnings

# macOS system Python ships LibreSSL; urllib3 v2 warns about it on import.
# The warning is harmless for local HTTP calls, so keep the demo output clean.
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")
