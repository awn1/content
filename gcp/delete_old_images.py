from gcp import Images, creds
import argparse


def options_handler():
    parser = argparse.ArgumentParser(description='A script that deletes old images according to the filter string and '
                                                 'number of images to reserve')
    parser.add_argument('--server-version',
                        help='The filter string with which the images will be fetched',
                        required=True,
                        type=str)
    parser.add_argument('--images-to-reserve',
                        help='The number of images to reserve, images reserved will be the last ones',
                        required=True,
                        type=int)
    parser.add_argument('--creds',
                        help='GCP creds',
                        required=True,
                        type=str)
    options = parser.parse_args()
    return options


def main():
    options = options_handler()
    Images(options.creds).delete(
        options.server_version, options.images_to_reserve)


if __name__ == '__main__':
    main()
