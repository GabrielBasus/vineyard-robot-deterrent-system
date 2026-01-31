from setuptools import find_packages, setup
from os.path import join

package_name = 'bird_deterrent_vineyard'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test', 'bird-deterrent-vineyard']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        (join('share', package_name), ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='gabrielbasus',
    maintainer_email='gabriel.basus@yahoo.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'central_coordinator = bird_deterrent_vineyard.central_coordinator:main',
            'robot_executor = bird_deterrent_vineyard.robot_executor:main',
        ],
    },
)
