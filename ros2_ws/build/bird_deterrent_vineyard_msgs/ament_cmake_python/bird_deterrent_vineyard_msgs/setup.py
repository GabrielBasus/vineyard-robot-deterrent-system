from setuptools import find_packages
from setuptools import setup

setup(
    name='bird_deterrent_vineyard_msgs',
    version='0.0.0',
    packages=find_packages(
        include=('bird_deterrent_vineyard_msgs', 'bird_deterrent_vineyard_msgs.*')),
)
