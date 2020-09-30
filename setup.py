from setuptools import setup


setup(
    name="probostitcher",
    version="0.1",
    description="Combine video files using a JSON file as directions",
    author="Silvio Tomatis",
    author_email="silviot@gmail.com",
    license="GPL",
    install_requires=["ffmpeg-python", "pendulum"],
    entry_points={
        "console_scripts": [
            "probostitcher = probostitcher.server:main",
        ],
    },
    packages=["probostitcher"],
    zip_safe=False,
)
