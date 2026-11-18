from setuptools import find_packages, setup

package_name = "lang_grounding_ros"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/ground_command.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Ansh Pethani",
    maintainer_email="ansh@todo.edu",
    description="Thin ROS 2 wrapper that serves the lang_grounding library as /ground_command.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "ground_command_node = lang_grounding_ros.ground_command_node:main",
        ],
    },
)
