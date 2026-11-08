"""run_all_tests.py -- run every unit test in the package.

Usage:  python run_all_tests.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))


def main():
    import test_stl
    import test_habituation
    import test_spec_value

    print("=" * 60)
    print("STL robustness monitor")
    print("=" * 60)
    test_stl.run_all()

    print("\n" + "=" * 60)
    print("Habituation model")
    print("=" * 60)
    test_habituation.run_all()

    print("\n" + "=" * 60)
    print("Mission spec + counterfactual task value")
    print("=" * 60)
    test_spec_value.run_all()

    print("\nAll test modules completed.")


if __name__ == "__main__":
    main()
