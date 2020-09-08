from setuptools import setup


setup(
    name="video-stitcher",
    version="0.1",
    description="Combine video files using a JSON file as directions",
    author="Silvio Tomatis",
    author_email="silviot@gmail.com",
    license="GPL",
    install_requires=["ffmpeg-python", "pendulum"],
    packages=["videostitcher"],
    zip_safe=False,
)
