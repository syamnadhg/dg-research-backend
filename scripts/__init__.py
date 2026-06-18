# Marks scripts/ as a package so setuptools ships dg-supervisor.env.example as
# package-data in the wheel (research.py reads it via Path(__file__).parent/
# "scripts"/"dg-supervisor.env.example" on first-run env seeding). The .py files
# here are standalone admin/dev tools run directly — nothing imports `scripts`,
# so this empty __init__ changes no runtime behavior.
