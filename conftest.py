def pytest_addoption(parser):
    parser.addoption(
        "--headed", 
        action="store_true", 
        default=False, 
        help="Run Playwright in headed mode (visible browser window)"
    )
    parser.addoption(
        "--slow-mo", 
        action="store", 
        default=0, 
        type=int, 
        help="Slow down Playwright operations by X milliseconds (great for headed debugging)"
    )