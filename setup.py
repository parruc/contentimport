from setuptools import setup

setup(
    name='contentimport.dipartimenti',
    version='0.4.dev0',
    description='Custom import based on collective.exportimport',
    url='https://github.com/starzel/contentimport',
    author='Philip Bauer',
    author_email='bauer@starzel.de',
    license='GPL version 2',
    classifiers=[
        "Environment :: Web Environment",
        "Framework :: Plone",
        "Framework :: Plone :: Addon",
        "Framework :: Plone :: 6.1",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",
    ],
    packages=['contentimport'],
    include_package_data=True,
    zip_safe=False,
    python_requires=">=3.10",
    entry_points={'z3c.autoinclude.plugin': ['target = plone']},
    install_requires=[
        "setuptools",
        "collective.exportimport",
        "beautifulsoup4",
        ],
    )
